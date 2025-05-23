# -*- coding: utf-8 -*-
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

# TODO: Add Tests for both controller classes
import logging
from typing import Optional

from paas_wl.bk_app.cnative.specs.procs.exceptions import ProcNotFoundInRes
from paas_wl.bk_app.cnative.specs.procs.replicas import BkAppProcScaler
from paas_wl.bk_app.deploy.app_res.controllers import ProcAutoscalingHandler, ProcessesHandler
from paas_wl.bk_app.processes.constants import DEFAULT_CNATIVE_MAX_REPLICAS, ProcessTargetStatus
from paas_wl.bk_app.processes.controllers import ProcControllerHub
from paas_wl.bk_app.processes.exceptions import ProcessNotFound, ScaleProcessError
from paas_wl.bk_app.processes.models import ProcessSpec
from paas_wl.infras.cluster.constants import ClusterFeatureFlag
from paas_wl.infras.cluster.utils import get_cluster_by_app
from paas_wl.infras.resources.base.base import get_client_by_cluster_name
from paas_wl.infras.resources.base.kres import KDeployment
from paas_wl.infras.resources.generation.mapper import get_mapper_proc_config_latest
from paas_wl.infras.resources.generation.version import get_proc_deployment_name
from paas_wl.workloads.autoscaling.entities import AutoscalingConfig, ScalingObjectRef
from paas_wl.workloads.autoscaling.exceptions import AutoscalingUnsupported
from paas_wl.workloads.autoscaling.kres_entities import ProcAutoscaling
from paasng.platform.applications.constants import ApplicationType
from paasng.platform.applications.models import ModuleEnvironment
from paasng.platform.bkapp_model.manager import ModuleProcessSpecManager
from paasng.platform.bkapp_model.models import ModuleProcessSpec

logger = logging.getLogger(__name__)


class AppProcessesController:
    """Controls app's processes, includes common operations such as
    "start", "stop" and "scale", this class will update both the "ProcessSpec"(persistent
    structure in database) and the related resources in Cluster.

    Only support default applications.
    """

    def __init__(self, env: ModuleEnvironment):
        self.app = env.wl_app
        self.env = env
        self.handler = ProcessesHandler.new_by_app(self.app)
        self.autoscaling_handler = ProcAutoscalingHandler.new_by_app(self.app)

    def start(self, proc_type: str):
        """Start a process, WILL update the service if necessary

        :param proc_type: process type
        :raise: ScaleProcessError when error occurs
        """
        spec_updater = ProcSpecUpdater(self.env, proc_type)
        spec_updater.set_start()
        proc_spec = spec_updater.spec_object
        try:
            proc_config = get_mapper_proc_config_latest(self.app, proc_spec.name)
            self.handler.scale(proc_config, proc_spec.target_replicas)
        except Exception as e:
            raise ScaleProcessError(proc_type=proc_spec.name, exception=e)

    def stop(self, proc_type: str):
        """Stop a process by setting replicas to zero, WILL NOT delete the service.

        :param proc_type: process type
        :raise: ScaleProcessError when error occurs
        """
        spec_updater = ProcSpecUpdater(self.env, proc_type)
        spec_updater.set_stop()
        proc_spec = spec_updater.spec_object
        try:
            proc_config = get_mapper_proc_config_latest(self.app, proc_spec.name)
            self.handler.shutdown(proc_config)
        except Exception as e:
            raise ScaleProcessError(proc_type=proc_spec.name, exception=e)

    def scale(
        self,
        proc_type: str,
        autoscaling: bool = False,
        target_replicas: Optional[int] = None,
        scaling_config: Optional[AutoscalingConfig] = None,
    ):
        """Scale process to the `target_replicas` or set an autoscaling policy."""
        cluster = get_cluster_by_app(self.app)
        if not cluster.has_feature_flag(ClusterFeatureFlag.ENABLE_AUTOSCALING):
            if not autoscaling:
                return self._scale(proc_type, target_replicas)

            raise AutoscalingUnsupported("autoscaling feature is not available in the current cluster.")

        scaling = self._build_proc_autoscaling(cluster.name, proc_type, autoscaling, scaling_config)
        if autoscaling:
            return self._deploy_autoscaling(scaling)

        self._disable_autoscaling(scaling)
        return self._scale(proc_type, target_replicas)

    def _scale(self, proc_type: str, target_replicas: Optional[int]):
        """Scale a process to target replicas, WILL update the service if necessary

        :param proc_type: process type
        :param target_replicas: the expected replicas, '0' for stop
        :raises: ValueError when target_replicas is too big
        """
        if target_replicas is None:
            raise ValueError("target_replicas required when scale process")

        spec_updater = ProcSpecUpdater(self.env, proc_type)
        spec_updater.change_replicas(target_replicas)

        # 旧镜像应用需要同步副本数到 ModuleProcessSpec 中
        try:
            ModuleProcessSpecManager(self.env.module).set_replicas(proc_type, self.env.environment, target_replicas)
        except Exception:
            logger.exception(f"Failed to sync replicas to ModuleProcessSpec for app({self.env.application.code})")

        proc_spec = spec_updater.spec_object
        try:
            proc_config = get_mapper_proc_config_latest(self.app, proc_spec.name)
            self.handler.scale(proc_config, proc_spec.target_replicas)
        except Exception as e:
            raise ScaleProcessError(proc_type=proc_spec.name, exception=e)

    def _deploy_autoscaling(self, scaling: ProcAutoscaling):
        """Set autoscaling policy for process"""
        proc_spec = self._get_spec(scaling.name)
        # 普通应用：最大副本数 <= 进程规格方案允许的最大副本数
        if scaling.spec.max_replicas > proc_spec.plan.max_replicas:
            raise ScaleProcessError(
                message=f"max_replicas in scaling config can't more than {proc_spec.plan.max_replicas}"
            )

        proc_spec.autoscaling = True
        proc_spec.scaling_config = AutoscalingConfig(
            min_replicas=scaling.spec.min_replicas, max_replicas=scaling.spec.max_replicas, policy="default"
        )
        proc_spec.save(update_fields=["autoscaling", "scaling_config", "updated"])

        self.autoscaling_handler.deploy(scaling)

    def _disable_autoscaling(self, scaling: ProcAutoscaling):
        """Remove process's autoscaling policy"""
        proc_spec = self._get_spec(scaling.name)

        proc_spec.autoscaling = False
        proc_spec.save(update_fields=["autoscaling", "updated"])

        self.autoscaling_handler.delete(scaling)

    def _get_spec(self, proc_type: str) -> ProcessSpec:
        try:
            return ProcessSpec.objects.get(engine_app_id=self.app.uuid, name=proc_type)
        except ProcessSpec.DoesNotExist:
            raise ProcessNotFound(proc_type)

    def _build_proc_autoscaling(
        self, cluster_name: str, proc_type: str, autoscaling: bool, scaling_config: Optional[AutoscalingConfig]
    ) -> ProcAutoscaling:
        if autoscaling and not scaling_config:
            raise ValueError("scaling_config required when set autoscaling policy")

        kres_client = KDeployment(get_client_by_cluster_name(cluster_name), api_version="")
        target_ref = ScalingObjectRef(
            api_version=kres_client.get_preferred_version(),
            kind=kres_client.kind,
            name=get_proc_deployment_name(self.app, proc_type),
        )

        autoscaling_spec = scaling_config.to_autoscaling_spec() if scaling_config else None
        return ProcAutoscaling(self.app, proc_type, autoscaling_spec, target_ref)  # type: ignore


class CNativeProcController:
    """Process controller for cloud-native applications"""

    def __init__(self, env: ModuleEnvironment):
        self.env = env
        self.app = env.wl_app

    def start(self, proc_type: str):
        """Start a process"""
        module_process_spec = self._get_module_process_spec(proc_type)

        try:
            BkAppProcScaler(self.env).set_replicas(
                proc_type, module_process_spec.get_target_replicas(self.env.environment)
            )
        except ProcNotFoundInRes as e:
            raise ProcessNotFound(str(e))

    def stop(self, proc_type: str):
        """Stop a process."""
        try:
            BkAppProcScaler(self.env).set_replicas(proc_type, 0)
        except ProcNotFoundInRes as e:
            raise ProcessNotFound(str(e))

    def scale(
        self,
        proc_type: str,
        autoscaling: bool = False,
        target_replicas: Optional[int] = None,
        scaling_config: Optional[AutoscalingConfig] = None,
    ):
        """Scale process to the `target_replicas` or set an autoscaling policy.

        :param proc_type: The type of the process.
        :param autoscaling: Whether to enable autoscaling.
        :param target_replicas: The fixed target number of replicas.
        :param scaling_config: Not required if `autoscaling` is False, but when `autoscaling`
            is True, it's required when no old autoscaling config can be found in the database.
        """
        if autoscaling:
            self.scale_auto(proc_type, autoscaling, scaling_config)
        else:
            self.disable_autoscaling_if_enabled(proc_type)
            if target_replicas is not None:
                self.scale_static(proc_type, target_replicas)

    def scale_static(self, proc_type: str, target_replicas: int):
        """Scale process to the `target_replicas`."""
        if target_replicas > DEFAULT_CNATIVE_MAX_REPLICAS:
            raise ValueError(f"target_replicas can't be greater than {DEFAULT_CNATIVE_MAX_REPLICAS}")

        # Update the module specs also to keep the bkapp model in sync.
        ModuleProcessSpecManager(self.env.module).set_replicas(proc_type, self.env.environment, target_replicas)

        try:
            BkAppProcScaler(self.env).set_replicas(proc_type, target_replicas)
        except ProcNotFoundInRes as e:
            raise ProcessNotFound(str(e))

    def disable_autoscaling_if_enabled(self, proc_type: str):
        """Disable autoscaling if it's enabled."""
        module_process_spec = self._get_module_process_spec(proc_type)
        if module_process_spec.get_autoscaling(self.env.environment):
            self.scale_auto(proc_type, False)

    def scale_auto(self, proc_type: str, enabled: bool, scaling_config: Optional[AutoscalingConfig] = None):
        """Update autoscaling config for the given process."""
        if not enabled:
            ModuleProcessSpecManager(self.env.module).set_autoscaling(proc_type, self.env.environment, False)
            BkAppProcScaler(self.env).set_autoscaling(proc_type, False, None)
            return

        # Check the feature flag first
        cluster = get_cluster_by_app(self.app)
        if not cluster.has_feature_flag(ClusterFeatureFlag.ENABLE_AUTOSCALING):
            raise AutoscalingUnsupported("autoscaling feature is not available in the current cluster.")

        # Use the old config value when the scaling config is not provided.
        if not scaling_config:
            module_process_spec = self._get_module_process_spec(proc_type)
            scaling_config = module_process_spec.get_scaling_config(self.env.environment)
            if not scaling_config:
                raise AutoscalingUnsupported("autoscaling config is not set from the given proc_type.")

        ModuleProcessSpecManager(self.env.module).set_autoscaling(
            proc_type, self.env.environment, True, scaling_config
        )
        try:
            BkAppProcScaler(self.env).set_autoscaling(proc_type, True, scaling_config)
        except ProcNotFoundInRes as e:
            raise ProcessNotFound(str(e))
        return

    def _get_module_process_spec(self, proc_type: str):
        try:
            return ModuleProcessSpec.objects.get(module=self.env.module, name=proc_type)
        except ModuleProcessSpec.DoesNotExist:
            raise ProcessNotFound("module process spec not found")


class ProcSpecUpdater:
    """It update the ProcessSpec object for the given env and process type.

    :param env: The environment object.
    :param proc_type: The process type.
    """

    def __init__(self, env: ModuleEnvironment, proc_type: str):
        self.app = env.wl_app
        self.proc_type = proc_type

    def set_start(self):
        """Set the process to "start" state."""
        proc_spec = self.spec_object
        # Reset the replicas if it's 0.
        if proc_spec.target_replicas <= 0:
            proc_spec.target_replicas = 1
        proc_spec.target_status = ProcessTargetStatus.START.value
        proc_spec.save(update_fields=["target_replicas", "target_status", "updated"])

    def set_stop(self):
        """Set the process to "stop" state."""
        proc_spec = self.spec_object
        proc_spec.target_status = ProcessTargetStatus.STOP.value
        # 确保停止进程 / 下架时候的副本数不会超过套餐允许的最大副本数
        proc_spec.target_replicas = min(proc_spec.target_replicas, proc_spec.plan.max_replicas)
        proc_spec.save(update_fields=["target_status", "target_replicas", "updated"])

    def change_replicas(self, target_replicas: int):
        """Change the target_replicas value."""
        proc_spec = self.spec_object
        proc_spec.target_replicas = target_replicas
        proc_spec.target_status = (
            ProcessTargetStatus.START.value if target_replicas else ProcessTargetStatus.STOP.value
        )
        proc_spec.save(update_fields=["target_replicas", "target_status", "updated"])

    def set_autoscaling(self, enabled: bool, config: Optional[AutoscalingConfig] = None):
        """Set the autoscaling for the given process and environment."""
        proc_spec = self.spec_object
        proc_spec.autoscaling = enabled
        if config is not None:
            proc_spec.scaling_config = config
        proc_spec.save(update_fields=["autoscaling", "scaling_config", "updated"])

    @property
    def spec_object(self) -> ProcessSpec:
        """Get the ProcessSpec object"""
        try:
            return ProcessSpec.objects.get(engine_app_id=self.app.uuid, name=self.proc_type)
        except ProcessSpec.DoesNotExist:
            raise ProcessNotFound(self.proc_type)


# Register controllers
ProcControllerHub.register_controller(ApplicationType.DEFAULT, AppProcessesController)
ProcControllerHub.register_controller(ApplicationType.ENGINELESS_APP, AppProcessesController)
ProcControllerHub.register_controller(ApplicationType.CLOUD_NATIVE, CNativeProcController)
