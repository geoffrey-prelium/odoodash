# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_clientpreference'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlerteIndicateur',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('indicator_name', models.CharField(max_length=255, verbose_name='Indicateur')),
                ('comparator', models.CharField(choices=[('lt', '<'), ('lte', '<='), ('gt', '>'), ('gte', '>=')], max_length=3, verbose_name='Comparatif')),
                ('threshold', models.FloatField(verbose_name='Seuil')),
                ('collaborator_email', models.EmailField(max_length=254, verbose_name='Email Collaborateur Prelium')),
                ('is_active', models.BooleanField(default=True, verbose_name='Active')),
                ('last_alert_sent', models.DateTimeField(blank=True, null=True, verbose_name='Dernier mail envoyé')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.clientsodoo', verbose_name='Dossier')),
            ],
            options={
                'verbose_name': 'Alerte Indicateur',
                'verbose_name_plural': 'Alertes Indicateurs',
                'ordering': ['client__client_name', 'indicator_name'],
            },
        ),
    ]
