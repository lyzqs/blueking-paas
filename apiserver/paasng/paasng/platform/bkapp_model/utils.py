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

import copy
from typing import List

from blue_krill.data_types.enum import StrStructuredEnum

from paas_wl.bk_app.cnative.specs.crd.bk_app import EnvVar, EnvVarOverlay


class MergeStrategy(StrStructuredEnum):
    """Different strategy when merging env vars"""

    OVERRIDE = "Override"
    IGNORE = "Ignore"


def override_env_vars_overlay(x: List[EnvVarOverlay], y: List[EnvVarOverlay]):
    """Use env variable in y to override x, if y have the same (name, envName)

    if the var only in y but not in x, will never add into result
    """
    merged = copy.deepcopy(x)
    y_vars = {(var.name, var.envName): var.value for var in y}
    for var in merged:
        if (var.name, var.envName) in y_vars:
            value = y_vars.pop((var.name, var.envName))
            var.value = value

    return merged


def merge_env_vars_overlay(
    x: List[EnvVarOverlay], y: List[EnvVarOverlay], strategy: MergeStrategy = MergeStrategy.OVERRIDE
):
    """Merge two env variable list, if a conflict was found, will resolve it by the given strategy.

    Supported strategies:
    - MergeStrategy.OVERRIDE: will use the one in y if x and y have same name EnvVar
    - MergeStrategy.IGNORE: will ignore the EnvVar in y if x and y have same name EnvVar
    """
    merged = copy.deepcopy(x)
    y_vars = {(var.name, var.envName): var.value for var in y}
    for var in merged:
        if (var.name, var.envName) in y_vars:
            value = y_vars.pop((var.name, var.envName))
            if strategy == MergeStrategy.OVERRIDE:
                var.value = value

    for (name, env_name), value in y_vars.items():
        merged.append(EnvVarOverlay(name=name, value=value, envName=env_name))
    return merged


def merge_env_vars(x: List[EnvVar], y: List[EnvVar], strategy: MergeStrategy = MergeStrategy.OVERRIDE):
    """Merge two env variable list, if a conflict was found, will resolve it by the given strategy.

    Supported strategies:

    - MergeStrategy.OVERRIDE: will use the one in y if x and y have same name EnvVar
    - MergeStrategy.IGNORE: will ignore the EnvVar in y if x and y have same name EnvVar
    """
    merged = copy.deepcopy(x)
    y_vars = {var.name: var.value for var in y}
    for var in merged:
        if var.name in y_vars:
            value = y_vars.pop(var.name)
            if strategy == MergeStrategy.OVERRIDE:
                var.value = value

    for name, value in y_vars.items():
        merged.append(EnvVar(name=name, value=value))
    return merged
