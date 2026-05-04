# core/management/commands/check_alerts.py
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings as django_settings
from core.models import AlerteIndicateur, IndicateursHistoriques

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Vérifie les alertes sur les indicateurs et envoie les emails si les seuils sont atteints."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("\n--- Vérification des alertes sur indicateurs ---"))

        active_alerts = AlerteIndicateur.objects.filter(is_active=True).select_related('client')
        self.stdout.write(f"  Alertes actives trouvées: {active_alerts.count()}")
        alerts_sent = 0
        alerts_reset = 0

        for alert in active_alerts:
            self.stdout.write(f"\n  Alerte: {alert.client.client_name} | {alert.indicator_name} "
                              f"{alert.get_comparator_display()} {alert.threshold} | → {alert.collaborator_email}")

            # Récupérer la dernière valeur de l'indicateur pour ce client
            latest_indicator = IndicateursHistoriques.objects.filter(
                client=alert.client,
                indicator_name__iexact=alert.indicator_name
            ).order_by('-extraction_timestamp').first()

            if not latest_indicator:
                self.stdout.write(self.style.WARNING(f"    Aucun indicateur trouvé pour '{alert.indicator_name}', ignoré."))
                continue
            if not latest_indicator.indicator_value:
                self.stdout.write(self.style.WARNING(f"    Valeur vide pour '{alert.indicator_name}', ignoré."))
                continue

            self.stdout.write(f"    Valeur: '{latest_indicator.indicator_value}' "
                              f"(extraction: {latest_indicator.extraction_timestamp})")

            threshold_breached = alert.check_threshold(latest_indicator.indicator_value)
            self.stdout.write(f"    Seuil franchi: {threshold_breached}")

            if threshold_breached:
                # Vérifier la déduplication : pas de renvoi si mail envoyé il y a moins de 48h
                should_send = False
                if alert.last_alert_sent is None:
                    should_send = True
                else:
                    time_since_last = timezone.now() - alert.last_alert_sent
                    if time_since_last > timedelta(hours=48):
                        should_send = True
                    else:
                        self.stdout.write(f"    Dernier mail envoyé il y a {time_since_last}, ignoré (< 48h).")

                if should_send:
                    try:
                        subject = f"[OdooDash] Alerte: {alert.indicator_name} pour {alert.client.client_name}"
                        message = (
                            f"Bonjour,\n\n"
                            f"L'indicateur \"{alert.indicator_name}\" pour le dossier "
                            f"\"{alert.client.client_name}\" a atteint le seuil d'alerte.\n\n"
                            f"  • Valeur actuelle : {latest_indicator.indicator_value}\n"
                            f"  • Condition : {alert.get_comparator_display()} {alert.threshold}\n"
                            f"  • Date de l'extraction : {latest_indicator.extraction_timestamp.strftime('%d/%m/%Y %H:%M')}\n\n"
                            f"Cordialement,\n"
                            f"OdooDash"
                        )
                        send_mail(
                            subject,
                            message,
                            django_settings.DEFAULT_FROM_EMAIL,
                            [alert.collaborator_email],
                            fail_silently=False,
                        )
                        alert.last_alert_sent = timezone.now()
                        alert.save(update_fields=['last_alert_sent'])
                        alerts_sent += 1
                        self.stdout.write(self.style.WARNING(
                            f"    ⚠ EMAIL ENVOYÉ → {alert.collaborator_email}"
                        ))
                    except Exception as e_mail:
                        self.stderr.write(self.style.ERROR(
                            f"    ✗ Erreur envoi mail: {e_mail}"
                        ))
            else:
                # Le seuil n'est plus dépassé → reset pour que la prochaine alerte fonctionne
                if alert.last_alert_sent is not None:
                    alert.last_alert_sent = None
                    alert.save(update_fields=['last_alert_sent'])
                    alerts_reset += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"    ✓ Alerte réinitialisée (revenu sous le seuil)."
                    ))

        self.stdout.write(self.style.SUCCESS(
            f"\n--- Alertes: {alerts_sent} envoyée(s), {alerts_reset} réinitialisée(s) ---"
        ))
