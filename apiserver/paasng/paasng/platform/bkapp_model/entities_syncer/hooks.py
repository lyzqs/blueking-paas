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

from paasng.platform.bkapp_model.entities import Hooks
from paasng.platform.bkapp_model.models import DeployHookType, ModuleDeployHook
from paasng.platform.modules.models import Module

from .result import CommonSyncResult


def sync_hooks(module: Module, hooks: Hooks) -> CommonSyncResult:
    """Sync hooks data to db model

    :param module: app module
    :param hooks: hooks config
    :return: sync result
    """
    ret = CommonSyncResult()

    # Build the index of existing data first to remove data later.
    # Data structure: {hook type: pk}
    existing_index = {}
    for hook in ModuleDeployHook.objects.filter(module=module):
        existing_index[hook.type] = hook.pk

    # Update or create data
    if pre_release_hook := hooks.pre_release:
        _, created = ModuleDeployHook.objects.update_or_create(
            module=module,
            type=DeployHookType.PRE_RELEASE_HOOK,
            defaults={
                "command": pre_release_hook.command,
                "args": pre_release_hook.args,
                "enabled": True,
                # FIXME 处理 proc_command 与 command/args 的关系
                # proc_command 优先级高于 command/args，需要强制刷新掉
                "proc_command": None,
            },
        )
        ret.incr_by_created_flag(created)
        # Move out from the index
        existing_index.pop(DeployHookType.PRE_RELEASE_HOOK, None)

    # Remove existing data that is not touched.
    ret.deleted_num, _ = ModuleDeployHook.objects.filter(module=module, id__in=existing_index.values()).delete()
    return ret
