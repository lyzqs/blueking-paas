# TencentBlueKing is pleased to support the open source community by making
# 蓝鲸智云 - PaaS 平台 (BlueKing - PaaS System) available.
# Copyright (C) 2017 THL A29 Limited, a Tencent company. All rights reserved.
# Licensed under the MIT License (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
#     http://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
# We undertake not to change the open source license (MIT license) applicable
# to the current version of the project delivered to anyone in the future.

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

import arrow

from paas_wl.bk_app.applications.models import Build
from paas_wl.bk_app.cnative.specs.credentials import split_image
from paas_wl.bk_app.processes.models import ProcessSpec
from paas_wl.infras.cluster.utils import get_image_registry_by_app
from paas_wl.workloads.images.entities import ImageCredentialRef
from paasng.platform.applications.constants import ApplicationType
from paasng.platform.applications.models import ModuleEnvironment
from paasng.platform.engine.constants import RuntimeType
from paasng.platform.engine.models import Deployment
from paasng.platform.modules.helpers import ModuleRuntimeManager
from paasng.platform.modules.models import BuildConfig
from paasng.platform.modules.models.module import Module
from paasng.platform.modules.specs import ModuleSpecs
from paasng.platform.smart_app.conf import bksmart_settings
from paasng.platform.smart_app.services.image_mgr import SMartImageManager
from paasng.platform.sourcectl.constants import VersionType
from paasng.platform.sourcectl.models import RepoBasicAuthHolder

if TYPE_CHECKING:
    from paasng.platform.engine.models import EngineApp
    from paasng.platform.sourcectl.models import VersionInfo


def generate_image_repositories_by_module(module: Module) -> Dict[str, str]:
    """获取应用模块的镜像仓库地址（按环境划分）"""
    return {env.environment: generate_image_repository_by_env(env) for env in module.get_envs()}


def generate_image_repository_by_env(env: ModuleEnvironment) -> str:
    """通过部署环境来获取镜像仓库地址"""
    reg = get_image_registry_by_app(env.wl_app)
    tmpl = f"{reg.host}/{reg.namespace}/{{app_code}}/{{module_name}}"
    return tmpl.format(app_code=env.application.code, module_name=env.module.name)


def generate_image_tag(module: Module, version: "VersionInfo") -> str:
    """Get the Image Tag for version"""
    cfg = BuildConfig.objects.get_or_create_by_module(module)
    options = cfg.tag_options
    parts: List[str] = []
    if options.prefix:
        parts.append(options.prefix)
    if options.with_version:
        parts.append(version.version_name)
    if options.with_build_time:
        parts.append(arrow.now().format("YYMMDDHHmm"))
    if options.with_commit_id:
        parts.append(version.revision)
    tag = "-".join(parts)
    # 不符合 tag 正则的字符, 替换为 '-'
    tag_regex = re.compile("[^a-zA-Z0-9_.-]")
    tag = tag_regex.sub("-", tag)
    # 去掉开头的 '-'
    tag = re.sub("^-+", "", tag)
    return tag


def get_credential_refs(module: Module) -> List[ImageCredentialRef]:
    """get the valid user-defined image credential references"""
    build_config = BuildConfig.objects.get(module=module)
    if build_config.image_repository and build_config.image_credential_name:
        return [
            ImageCredentialRef(
                image=split_image(build_config.image_repository),
                credential_name=build_config.image_credential_name,
            )
        ]
    return []


@dataclass
class ImageCredential:
    registry: str
    username: str
    password: str


class ImageCredentialManager:
    """A Helper provide the image pull secret for the given Module"""

    def __init__(self, module: Module):
        self.module = module

    def provide(self) -> Optional[ImageCredential]:
        if ModuleSpecs(self.module).deploy_via_package:
            named = SMartImageManager(self.module).get_image_info()
            return ImageCredential(
                registry=f"{named.domain}/{named.name}",
                username=bksmart_settings.registry.username,
                password=bksmart_settings.registry.password,
            )
        source_obj = self.module.get_source_obj()
        repo_full_url = source_obj.get_repo_url()
        try:
            holder = RepoBasicAuthHolder.objects.get_by_repo(module=self.module, repo_obj=source_obj)
            username, password = holder.basic_auth
        except RepoBasicAuthHolder.DoesNotExist:
            username = password = None

        if repo_full_url and username and password:
            return ImageCredential(registry=repo_full_url, username=username, password=password)
        return None


class RuntimeImageInfo:
    """提供与当前应用匹配的运行时环境信息的工具"""

    def __init__(self, engine_app: "EngineApp"):
        self.engine_app = engine_app
        self.module: Module = engine_app.env.module
        self.application = self.module.application
        self.module_spec = ModuleSpecs(self.module)

    @property
    def type(self) -> RuntimeType:
        """返回当前 engine_app 的运行时的类型, buildpack 或者 custom_image"""
        return self.module_spec.runtime_type

    def generate_image(self, version_info: "VersionInfo", special_tag: Optional[str] = None) -> str:  # noqa: PLR0911
        """generate the runtime image of the application at a given version

        :param version_info: 版本信息
        :param special_tag: 指定镜像 Tag
        :return: 返回运行构建产物(Build)的镜像
                 如果构建产物是 Image, 则返回的是镜像
                 如果构建产物是 Slug, 则返回 SlugRunner 的镜像
        """
        if self.type == RuntimeType.CUSTOM_IMAGE:
            if self.application.type == ApplicationType.CLOUD_NATIVE:
                image_tag = special_tag or version_info.version_name
                repository = self.module.build_config.image_repository
                if not repository:
                    # v1alpha1 版本的云原生应用未存储 image_repository 字段
                    # 此处返回空字符串表示不覆盖 manifest 的 image 信息
                    return ""
                return f"{repository}:{image_tag}"
            repo_url = self.module.get_source_obj().get_repo_url()
            reference = version_info.revision
            return f"{repo_url}:{reference}"
        elif self.type == RuntimeType.DOCKERFILE:
            app_image_repository = generate_image_repository_by_env(self.engine_app.env)
            app_image_tag = special_tag or generate_image_tag(module=self.module, version=version_info)
            return f"{app_image_repository}:{app_image_tag}"
        elif (
            self.application.is_smart_app and version_info.version_type != VersionType.PACKAGE.value
        ):  # version_type 为 package 时, 表示采用二进制 slug.tgz 方案; image(已废弃) 和 tag 时, 表示镜像层方案
            from paasng.platform.smart_app.services.image_mgr import SMartImageManager

            named = SMartImageManager(self.module).get_image_info(version_info.revision)
            return f"{named.domain}/{named.name}:{named.tag}"
        mgr = ModuleRuntimeManager(self.module)
        slug_runner = mgr.get_slug_runner(raise_exception=False)
        if mgr.is_cnb_runtime:
            app_image_repository = generate_image_repository_by_env(self.engine_app.env)
            app_image_tag = special_tag or generate_image_tag(module=self.module, version=version_info)
            return f"{app_image_repository}:{app_image_tag}"
        return getattr(slug_runner, "full_image", "")


def update_image_runtime_config(deployment: Deployment):
    """Update the image runtime config of the given engine app"""
    engine_app = deployment.get_engine_app()
    build_obj = Build.objects.get(pk=deployment.build_id)
    image_pull_policy = deployment.advanced_options.image_pull_policy
    runtime = RuntimeImageInfo(engine_app=engine_app)
    runtime_dict = {
        "type": runtime.type,
        "image_pull_policy": image_pull_policy,
    }
    # TODO: 每个 slugrunner 可以配置镜像的 ENTRYPOINT
    mgr = ModuleRuntimeManager(deployment.app_environment.module)
    slug_runner = mgr.get_slug_runner(raise_exception=False)
    metadata: Dict = getattr(slug_runner, "metadata", {})
    if entrypoint := metadata.get("entrypoint"):
        build_obj.artifact_metadata.entrypoint = entrypoint
        build_obj.save(update_fields=["artifact_metadata", "updated"])

    # Update the config property of WlApp object
    wl_app = engine_app.to_wl_obj()
    config = wl_app.latest_config
    config.runtime = runtime_dict

    # Refresh resource requirements
    config.resource_requirements = {
        pack.name: pack.plan.get_resource_summary() for pack in ProcessSpec.objects.filter(engine_app_id=config.app.pk)
    }
    config.save(update_fields=["runtime", "updated", "resource_requirements"])
