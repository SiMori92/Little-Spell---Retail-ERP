from django.db import migrations, models


CONTROLS_SQL = """
CREATE OR REPLACE FUNCTION core_secretrotation_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'core_secretrotation is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER core_secretrotation_append_only
    BEFORE UPDATE OR DELETE ON core_secretrotation
    FOR EACH ROW EXECUTE FUNCTION core_secretrotation_append_only();

CREATE OR REPLACE FUNCTION core_dataset_kind_one_way() RETURNS trigger AS $$
BEGIN
    IF OLD.dataset_kind = 'ACTUAL' AND NEW.dataset_kind <> 'ACTUAL' THEN
        RAISE EXCEPTION 'dataset_kind is one-way: ACTUAL cannot be changed back to SAMPLE';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER core_dataset_kind_one_way
    BEFORE UPDATE OF dataset_kind ON core_datasetsettings
    FOR EACH ROW EXECUTE FUNCTION core_dataset_kind_one_way();
"""

DROP_CONTROLS_SQL = """
DROP TRIGGER IF EXISTS core_dataset_kind_one_way ON core_datasetsettings;
DROP FUNCTION IF EXISTS core_dataset_kind_one_way();
DROP TRIGGER IF EXISTS core_secretrotation_append_only ON core_secretrotation;
DROP FUNCTION IF EXISTS core_secretrotation_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0006_business_tax_regime")]

    operations = [
        migrations.CreateModel(
            name="SecretRotation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rotated_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.CharField(max_length=120)),
                ("evidence_ref", models.CharField(max_length=255)),
                ("secret_key_sha256", models.CharField(max_length=64)),
                ("db_password_rotated", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ("-rotated_at", "-id"),
                "constraints": [
                    models.CheckConstraint(condition=~models.Q(actor=""), name="core_rotation_actor_required"),
                    models.CheckConstraint(condition=~models.Q(evidence_ref=""), name="core_rotation_evidence_required"),
                    models.CheckConstraint(condition=models.Q(secret_key_sha256__regex=r"^[0-9a-f]{64}$"), name="core_rotation_sha256_shape"),
                ],
            },
        ),
        migrations.RunSQL(CONTROLS_SQL, DROP_CONTROLS_SQL),
    ]
