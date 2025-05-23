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

from django.conf import settings
from rest_framework import permissions

from paasng.infras.accounts.constants import AccountFeatureFlag as AccountFeatureFlagConst
from paasng.infras.accounts.constants import SiteRole
from paasng.infras.accounts.models import AccountFeatureFlag, User, UserProfile


def user_has_feature(key: AccountFeatureFlagConst):
    """A factory function which generates a Permission class for account feature flag"""

    class Permission(permissions.BasePermission):
        def has_permission(self, request, view):
            return AccountFeatureFlag.objects.has_feature(request.user, key)

    return Permission


def user_can_operate_in_region(user: User, region: str) -> bool:
    """校验用户对指定版本的操作权限，主要应用于：
    - 应用创建
    - 模块创建
    - 自定义访问地址管理

    :param user: 待校验的用户对象
    :param region: 目标区域名称
    :return: 是否具有操作权限

    权限规则：
    - 默认版本（DEFAULT_REGION_NAME）：所有用户都可以操作
    - 非默认版本：仅允许管理员操作
    """
    if region == settings.DEFAULT_REGION_NAME:
        return True

    user_profile = UserProfile.objects.get_profile(user)
    return user_profile.role in {SiteRole.ADMIN.value, SiteRole.SUPER_USER.value}
