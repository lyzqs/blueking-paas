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

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status

from paas_wl.infras.cluster.constants import ClusterFeatureFlag

pytestmark = pytest.mark.django_db(databases=["default", "workloads"])


class TestClusterDefaultConfigViewSet:
    """获取集群默认配置"""

    def test_list(self, plat_mgt_api_client, init_default_cluster):
        resp = plat_mgt_api_client.get(reverse("plat_mgt.infras.cluster_default_config.list"))
        assert resp.status_code == status.HTTP_200_OK

        assert resp.json() == {
            "image_repository": f"{settings.APP_DOCKER_REGISTRY_HOST}/{settings.APP_DOCKER_REGISTRY_NAMESPACE}",
            "feature_flags": {
                ClusterFeatureFlag.ENABLE_MOUNT_LOG_TO_HOST: True,
                ClusterFeatureFlag.INGRESS_USE_REGEX: False,
                ClusterFeatureFlag.ENABLE_BK_MONITOR: False,
                ClusterFeatureFlag.ENABLE_BK_LOG_COLLECTOR: False,
                ClusterFeatureFlag.ENABLE_AUTOSCALING: False,
                ClusterFeatureFlag.ENABLE_BCS_EGRESS: False,
            },
        }
