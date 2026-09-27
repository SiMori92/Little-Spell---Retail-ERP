from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("ops", "0009_igdealstatus_igdeal")]

    operations = [
        migrations.AddConstraint(
            model_name="igdeal",
            constraint=models.CheckConstraint(
                condition=(
                    (models.Q(quoted_at__isnull=True) |
                     models.Q(quoted_at__gte=models.F("enquiry_at"))) &
                    (models.Q(paid_at__isnull=True) |
                     models.Q(paid_at__gte=models.F("enquiry_at"))) &
                    (models.Q(ship_date__isnull=True) |
                     models.Q(ship_date__gte=models.F("enquiry_at"))) &
                    (models.Q(quoted_at__isnull=True) | models.Q(paid_at__isnull=True) |
                     models.Q(paid_at__gte=models.F("quoted_at"))) &
                    (models.Q(quoted_at__isnull=True) | models.Q(ship_date__isnull=True) |
                     models.Q(ship_date__gte=models.F("quoted_at"))) &
                    (models.Q(paid_at__isnull=True) | models.Q(ship_date__isnull=True) |
                     models.Q(ship_date__gte=models.F("paid_at"))) &
                    (models.Q(follow_up_on__isnull=True) |
                     models.Q(follow_up_on__gte=models.F("enquiry_at")))
                ),
                name="ops_igdeal_date_order",
            ),
        ),
    ]
