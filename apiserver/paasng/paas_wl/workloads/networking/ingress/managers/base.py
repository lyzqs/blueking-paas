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

import abc
import logging
from typing import Dict, List, Optional, Sequence, Type

from paas_wl.bk_app.applications.models import WlApp
from paas_wl.core.app_structure import has_proc_type
from paas_wl.infras.resources.kube_res.exceptions import AppEntityNotFound
from paas_wl.workloads.networking.ingress.entities import PIngressDomain
from paas_wl.workloads.networking.ingress.exceptions import DefaultServiceNameRequired, EmptyAppIngressError
from paas_wl.workloads.networking.ingress.kres_entities.ingress import ProcessIngress, ingress_kmodel
from paas_wl.workloads.networking.ingress.kres_entities.service import service_kmodel
from paas_wl.workloads.networking.ingress.managers.ing_class import get_ingress_class_by_wl_app
from paas_wl.workloads.networking.ingress.plugins import get_default_plugins
from paas_wl.workloads.networking.ingress.plugins.exceptions import PluginNotConfigured
from paas_wl.workloads.networking.ingress.plugins.ingress import IngressPlugin
from paas_wl.workloads.networking.ingress.utils import parse_process_type

logger = logging.getLogger(__name__)


class AppIngressMgr(abc.ABC):
    """Simple class for managing app ingress"""

    # An optional extra plugins among the default plugins
    plugins: List[Type[IngressPlugin]] = []

    # The value of `rewrite_to_root` when syncing Ingress resource, see `ProcessIngress` for
    # more details, enabled by default.
    rewrite_ingress_path_to_root: bool = True

    # Whether to set header `X-Script-Name` to all request
    set_header_x_script_name: bool = True

    def __init__(self, app: "WlApp"):
        self.app = app
        self.ingress_name = self.make_ingress_name()
        self.ingress_updater = IngressUpdater(self.app, self.ingress_name)

    def get(self) -> ProcessIngress:
        """Return the default ingress object"""
        return ingress_kmodel.get(self.app, self.ingress_name)

    def delete(self):
        """Delete the default ingress rule"""
        ingress_kmodel.delete_by_name(self.app, self.ingress_name, non_grace_period=True)

    def sync(self, default_service_name: Optional[str] = None, delete_when_empty: bool = False):
        """Sync with kubernetes apiserver

        :param delete_when_empty: when True, will try to delete ingress object if it has no domains,
            default to False
        """
        domains = self.list_desired_domains()
        if not domains:
            if delete_when_empty:
                self.delete()
                return
            raise EmptyAppIngressError("no domains(rules with path) found for current ingress")

        self.ingress_updater.sync(
            domains,
            default_service_name=default_service_name,
            server_snippet=self.construct_server_snippet(domains),
            configuration_snippet=self.construct_configuration_snippet(domains),
            annotations=self.get_annotations(),
            rewrite_to_root=self.rewrite_ingress_path_to_root,
            set_header_x_script_name=self.set_header_x_script_name,
        )

    def update_target(self, service_name: str, service_port_name: str):
        """Update target service and port_name for current ingress resource"""
        self.ingress_updater.update_target(service_name, service_port_name)

    @abc.abstractmethod
    def make_ingress_name(self) -> str:
        """make the ingress resource name

        * template method, override in subclass
        """
        raise NotImplementedError

    def list_desired_domains(self) -> List[PIngressDomain]:
        """List all desired domains for current app

        * template method, override in subclass
        """
        return []

    def construct_server_snippet(self, domains: Sequence[PIngressDomain]) -> str:
        """Construct server snippet, this method will call registered plugins

        :params domains: current ingress domain objects
        """
        return self._get_plugins_snippets("server", domains)

    def construct_configuration_snippet(self, domains: Sequence[PIngressDomain]) -> str:
        """Construct configuration snippet, this method will call registered plugins

        :params domains: current ingress domain objects
        """
        return self._get_plugins_snippets("configuration", domains)

    def _get_plugins_snippets(self, snippet_type: str, domains: Sequence[PIngressDomain]) -> str:
        """Get snippets set by plugins

        :param snippet_type: server / configuration
        :params domains: current ingress domain objects
        """
        func_name = f"make_{snippet_type}_snippet"
        snippets = []
        for plugin_cls in self.get_plugins():
            try:
                func = getattr(plugin_cls(self.app, domains), func_name)
                snippets.append(func())
            except PluginNotConfigured:
                logger.debug("Plugin: %s not configured, skip processing.")
        return "\n".join([s for s in snippets if s])

    def get_plugins(self) -> List[Type[IngressPlugin]]:
        """Return plugins for current manager"""
        return get_default_plugins() + self.plugins

    def get_annotations(self) -> Dict:
        """Construct resource annotations"""
        annotations = {}

        # ingressClassName
        if ingress_cls_name := get_ingress_class_by_wl_app(self.app):
            annotations["kubernetes.io/ingress.class"] = ingress_cls_name

        return annotations


class IngressUpdater:
    """Helper class for updating ingress object"""

    # the hard-coded default port name, does not support modification yet
    DEFAULT_PORT_NAME = "http"

    def __init__(self, app: "WlApp", ingress_name: str):
        self.app = app
        self.ingress_name = ingress_name

    def sync(
        self,
        domains: List[PIngressDomain],
        default_service_name: Optional[str] = None,
        server_snippet: str = "",
        configuration_snippet: str = "",
        annotations: Optional[Dict] = None,
        rewrite_to_root: bool = True,
        set_header_x_script_name: bool = True,
        restore_default_when_invalid: bool = True,
    ):
        """Sync current ingress resource with kubernetes apiserver

        :param domains: domain infos
        :param default_service_name: the service current ingress binding to, only required when ingress
            does not exists and a creation is required.
        :param server_snippet: server snippet
        :param configuration_snippet: configuration snippet
        :param annotations: ingress annotations
        :param rewrite_to_root: whether to remove matched path prefix, which means rewrite path to "/(.*)"
        :param set_header_x_script_name: whether to set http header `X-Script-Name`,
            which means the sub-path provided by platform or custom domain
        :param restore_default_when_invalid: If the ingress resource exists and it's using an invalid
            service, restore the service name to default, enabled by default.
        :raises: DefaultServiceNameRequired when no default service name is given
        :raises: EmptyAppIngressError no domains are found
        """
        if not domains:
            raise EmptyAppIngressError("no domains(rules) found for current ingress")

        try:
            ingress = ingress_kmodel.get(self.app, self.ingress_name)
        except AppEntityNotFound:
            if not default_service_name:
                raise DefaultServiceNameRequired("no existed ingress found, default_server_name is required")

            logger.info("Creating new default ingress<%s> with service<%s>", self.ingress_name, default_service_name)
            desired_ingress = ProcessIngress(
                app=self.app,
                name=self.ingress_name,
                service_name=default_service_name,
                service_port_name=self.DEFAULT_PORT_NAME,
                domains=domains,
                server_snippet=server_snippet,
                configuration_snippet=configuration_snippet,
                annotations=annotations or {},
                rewrite_to_root=rewrite_to_root,
                set_header_x_script_name=set_header_x_script_name,
            )
            ingress_kmodel.save(desired_ingress)
        else:
            if (
                restore_default_when_invalid
                and default_service_name
                and not self._service_name_valid(ingress.service_name)
            ):
                # Restore service name to default if it's invalid
                logger.info(
                    "Restore service name to default, ingress: %s, current name: %s, new name: %s",
                    ingress.name,
                    ingress.service_name,
                    default_service_name,
                )
                ingress.service_name = default_service_name

            logger.info("Updating existed ingress<%s>", ingress.name)
            ingress.domains = domains
            ingress.server_snippet = server_snippet
            ingress.configuration_snippet = configuration_snippet
            ingress.annotations = annotations or {}
            ingress.rewrite_to_root = rewrite_to_root
            ingress.set_header_x_script_name = set_header_x_script_name
            ingress_kmodel.save(ingress)

    def update_target(self, service_name: str, service_port_name: str):
        """Update target service and port_name for current ingress resource"""
        ingress = ingress_kmodel.get(self.app, self.ingress_name)
        logger.info(
            f"updating existed ingress<{ingress.name}>, set service_name={service_name} port_name={service_port_name}"
        )
        ingress.service_name = service_name
        ingress.service_port_name = service_port_name
        ingress_kmodel.save(ingress)

    def _service_name_valid(self, name: str) -> bool:
        """Check that a service name is valid."""
        try:
            proc_type = parse_process_type(self.app, name)
        except ValueError:
            return True

        svc_names = [s.name for s in service_kmodel.list_by_app(self.app)]
        # A service name was considered invalid if it pointed to a non-existent service
        # and the process type(parsed from the name itself) didn't exist.
        #
        # Why check both conditions? An ingress could be created before the service object,
        # so the process type was also checked to avoid an unintended result.
        return name in svc_names or has_proc_type(self.app, proc_type)
