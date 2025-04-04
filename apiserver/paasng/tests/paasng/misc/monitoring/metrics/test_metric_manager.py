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

import datetime
from collections import namedtuple
from typing import List
from unittest.mock import Mock, patch

import pytest
from django.conf import settings

from paas_wl.bk_app.processes.managers import AppProcessManager
from paasng.misc.monitoring.metrics.clients import BkMonitorMetricClient
from paasng.misc.monitoring.metrics.constants import MetricsResourceType, MetricsSeriesType
from paasng.misc.monitoring.metrics.exceptions import RequestMetricBackendError
from paasng.misc.monitoring.metrics.models import ResourceMetricManager
from paasng.misc.monitoring.metrics.utils import MetricSmartTimeRange
from tests.paas_wl.utils.wl_app import create_wl_app, create_wl_instance, create_wl_release

pytestmark = pytest.mark.django_db(databases=["default", "workloads"])


class TestResourceMetricManager:
    @pytest.fixture(autouse=True)
    def _set_up(self) -> None:
        self.app = create_wl_app(force_app_info={"region": settings.DEFAULT_REGION_NAME})
        create_wl_release(wl_app=self.app)
        self.web_process = AppProcessManager(app=self.app).assemble_process("web")
        self.worker_process = AppProcessManager(app=self.app).assemble_process("worker")
        self.web_process.instances = [create_wl_instance(self.app), create_wl_instance(self.app)]
        self.worker_process.instances = [create_wl_instance(self.app)]

    @pytest.fixture()
    def metric_client(self, tenant_id):
        return BkMonitorMetricClient(bk_biz_id="123", tenant_id=tenant_id)

    def test_normal_gen_series_query(self, metric_client):
        manager = ResourceMetricManager(process=self.web_process, metric_client=metric_client, bcs_cluster_id="")
        fake_metrics_value = [[1234, 1234], [1234, 1234], [1234, 1234]]
        query_range_mock = Mock(return_value=fake_metrics_value)
        with patch("paasng.misc.monitoring.metrics.clients.BkMonitorMetricClient._query_range", query_range_mock):
            result = list(
                manager.get_all_instances_metrics(
                    time_range=MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58"),
                    resource_types=[MetricsResourceType.MEM],
                )
            )

            assert len(result) == 2
            assert result[0].results[0].type_name == "mem"
            assert result[0].results[0].results[0].type_name == "current"
            assert result[0].results[0].results[0].results == fake_metrics_value

    def test_empty_gen_series_query(self, metric_client):
        manager = ResourceMetricManager(process=self.web_process, metric_client=metric_client, bcs_cluster_id="")
        fake_metrics_value: List = []
        query_range_mock = Mock(return_value=fake_metrics_value)
        with patch("paasng.misc.monitoring.metrics.clients.BkMonitorMetricClient._query_range", query_range_mock):
            result = list(
                manager.get_all_instances_metrics(
                    time_range=MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58"),
                    resource_types=[MetricsResourceType.MEM],
                )
            )

            assert result[0].results[0].type_name == "mem"
            assert result[0].results[0].results[0].type_name == "current"
            assert result[0].results[0].results[0].results == fake_metrics_value

    def test_exception_gen_series_query(self, metric_client):
        manager = ResourceMetricManager(process=self.web_process, metric_client=metric_client, bcs_cluster_id="")
        FakeResponse = namedtuple("FakeResponse", "status_code")

        query_range_mock = Mock(side_effect=RequestMetricBackendError(FakeResponse(status_code=400)))
        with patch("paasng.misc.monitoring.metrics.clients.BkMonitorMetricClient._query_range", query_range_mock):
            result = list(
                manager.get_all_instances_metrics(
                    time_range=MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58"),
                    resource_types=[MetricsResourceType.MEM],
                )
            )

            assert len(result) == 2

    def test_gen_series_query(self, metric_client):
        temp_process = self.worker_process
        temp_process.instances[0].name = f"{settings.DEFAULT_REGION_NAME}-test-test-stag-asdfasdf"
        manager = ResourceMetricManager(process=temp_process, metric_client=metric_client, bcs_cluster_id="")
        query = manager.gen_series_query(
            instance_name=temp_process.instances[0].name,
            resource_type=MetricsResourceType.MEM,
            series_type=MetricsSeriesType.CURRENT,
            time_range=MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58"),
        )

        assert query.type_name == "current"
        assert query.query.startswith(
            "sum by(container_name)(container_memory_working_set_bytes{"
            f'pod_name="{settings.DEFAULT_REGION_NAME}-test-test-stag-asdfasdf",container_name!="POD",'
        )

    def test_gen_all_series_query(self, metric_client):
        manager = ResourceMetricManager(process=self.web_process, metric_client=metric_client, bcs_cluster_id="")
        queries = manager.gen_all_series_query(
            instance_name=self.web_process.instances[0].name,
            resource_type=MetricsResourceType.MEM,
            time_range=MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58"),
        )

        assert len(list(queries)) == 2


class TestTimeRange:
    def test_simple_date_string(self):
        tr = MetricSmartTimeRange(start="2013-05-11 21:23:58", end="2013-05-11 21:25:58")

        assert tr.start == "1368278638"
        assert tr.end == "1368278758"

    def test_to_now(self):
        tr = MetricSmartTimeRange(
            start="2013-05-11 21:23:58", end="2013-05-11 21:25:58", time_range_str=datetime.timedelta(hours=1)
        )

        assert tr.start != "1368278638"
        assert tr.end != "1368278758"

        # 精确到秒
        assert int(tr.end) - int(tr.start) == 3600
