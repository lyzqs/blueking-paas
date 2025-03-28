# Generated by Django 4.2.17 on 2025-01-09 01:57

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingress", "0008_alter_domain_https_enabled"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="appdomain",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="appsubpath",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="domain",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="appdomain",
            name="tenant_id",
            field=models.CharField(
                default="default",
                help_text="本条数据的所属租户",
                max_length=32,
                verbose_name="租户 ID",
            ),
        ),
        migrations.AddField(
            model_name="appdomaincert",
            name="tenant_id",
            field=models.CharField(
                default="default",
                help_text="本条数据的所属租户",
                max_length=32,
                verbose_name="租户 ID",
            ),
        ),
        migrations.AddField(
            model_name="appdomainsharedcert",
            name="tenant_id",
            field=models.CharField(
                default="default",
                help_text="本条数据的所属租户",
                max_length=32,
                verbose_name="租户 ID",
            ),
        ),
        migrations.AddField(
            model_name="appsubpath",
            name="tenant_id",
            field=models.CharField(
                default="default",
                help_text="本条数据的所属租户",
                max_length=32,
                verbose_name="租户 ID",
            ),
        ),
        migrations.AddField(
            model_name="domain",
            name="tenant_id",
            field=models.CharField(
                default="default",
                help_text="本条数据的所属租户",
                max_length=32,
                verbose_name="租户 ID",
            ),
        ),
        migrations.AlterField(
            model_name="appdomain",
            name="path_prefix",
            field=models.CharField(
                default="/",
                help_text="the accessible path for current domain",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="appdomain",
            name="source",
            field=models.IntegerField(help_text="数据来源分类"),
        ),
        migrations.AlterField(
            model_name="appdomaincert",
            name="name",
            field=models.CharField(
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
                    )
                ],
            ),
        ),
        migrations.AlterField(
            model_name="appdomainsharedcert",
            name="name",
            field=models.CharField(
                max_length=128,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
                    )
                ],
            ),
        ),
        migrations.AlterField(
            model_name="domain",
            name="path_prefix",
            field=models.CharField(
                default="/",
                help_text="the accessible path for current domain",
                max_length=64,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="appdomain",
            unique_together={("tenant_id", "host", "path_prefix")},
        ),
        migrations.AlterUniqueTogether(
            name="appdomaincert",
            unique_together={("tenant_id", "name")},
        ),
        migrations.AlterUniqueTogether(
            name="appdomainsharedcert",
            unique_together={("tenant_id", "name")},
        ),
        migrations.AlterUniqueTogether(
            name="appsubpath",
            unique_together={("tenant_id", "subpath")},
        ),
        migrations.AlterUniqueTogether(
            name="domain",
            unique_together={
                ("tenant_id", "name", "path_prefix", "module_id", "environment_id")
            },
        ),
    ]
