# Generated for Slice G-2 on 2026-09-27.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_alter_auditlogentry_actor_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='datasetsettings',
            name='business_tax_regime',
            field=models.CharField(choices=[('unregistered', 'unregistered'), ('assessed', 'assessed'), ('general', 'general')], db_default='unregistered', default='unregistered', help_text='unregistered | assessed | general. Set by manage.py set_business_tax_regime.', max_length=12),
        ),
        migrations.AddConstraint(
            model_name='datasetsettings',
            constraint=models.CheckConstraint(condition=models.Q(('business_tax_regime__in', ('unregistered', 'assessed', 'general'))), name='core_business_tax_regime_allowed'),
        ),
    ]
