"""
Firebase Cloud Messaging (FCM) Notifier
Sends push notifications to mobile devices
"""

import base64
import json
import logging
from typing import Dict, List, Optional
import firebase_admin
from firebase_admin import credentials, messaging

from config import (
    FIREBASE_CREDENTIALS_PATH, FCM_DEVICE_TOKEN, ENABLE_FCM_NOTIFICATION, REPORT_PAGE_URL
)

logger = logging.getLogger(__name__)


def _load_credentials(value: str):
    """
    Build Firebase credentials from FIREBASE_CREDENTIALS

    The value is either a path to a service account key file (local use) or the
    JSON content itself (GitHub Actions secret, where no key file exists).
    """
    if value.lstrip().startswith('{'):
        return credentials.Certificate(json.loads(value))
    return credentials.Certificate(value)


def _build_report_link(report_data: Dict) -> Optional[str]:
    """
    Build the URL opened when the notification is tapped

    The report travels in the URL fragment as base64url JSON, so the static report page
    needs no backend and nothing has to be committed. The page must be on the same host
    as the service worker, otherwise the Firebase SDK ignores the link.

    Returns:
        str: Report page URL, or None if REPORT_PAGE_URL is not configured
    """
    if not REPORT_PAGE_URL:
        return None

    rows = []
    for ticker, data in (report_data.get('stock_data') or {}).items():
        error = str(data['error'])[:80] if data.get('error') else None
        rows.append([
            ticker, data.get('price'), data.get('previous_close'), data.get('change'),
            data.get('change_percent'), data.get('volume'), error,
        ])

    payload = {'v': 1, 't': report_data.get('timestamp', ''), 's': rows}
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return f"{REPORT_PAGE_URL}#{base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')}"


class FCMNotifier:
    """
    Firebase Cloud Messaging notifier for sending push notifications
    """
    
    def __init__(self):
        """Initialize FCM connection"""
        self.initialized = False
        self.device_tokens = []
        
        if not ENABLE_FCM_NOTIFICATION:
            logger.warning("FCM notifications are disabled")
            return
        
        if not FCM_DEVICE_TOKEN:
            logger.warning("No FCM device token configured")
            return
        
        try:
            # Initialize Firebase Admin SDK
            if not firebase_admin._apps:
                cred = _load_credentials(FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)
            
            self.device_tokens = [FCM_DEVICE_TOKEN]
            self.initialized = True
            logger.info("FCM notifier initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize FCM: {str(e)}")
            logger.info("Make sure FIREBASE_CREDENTIALS is a valid key file path or key JSON")
    
    def send_notification(
        self,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        tokens: Optional[List[str]] = None,
        link: Optional[str] = None
    ) -> bool:
        """
        Send notification via FCM
        
        Args:
            title: Notification title
            body: Notification body/message
            data: Optional data dictionary
            tokens: List of device tokens (uses configured tokens if None)
            link: Optional https URL opened when the notification is tapped
        
        Returns:
            bool: True if notification sent successfully
        """
        if not self.initialized:
            logger.warning("FCM notifier not initialized, skipping notification")
            return False
        
        if not tokens:
            tokens = self.device_tokens
        
        if not tokens:
            logger.error("No device tokens available")
            return False
        
        try:
            # Without a link, tapping the notification only dismisses it
            webpush = None
            if link:
                webpush = messaging.WebpushConfig(
                    fcm_options=messaging.WebpushFCMOptions(link=link)
                )

            # Create notification
            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                data=data or {},
                webpush=webpush,
                tokens=tokens
            )
            
            # Send notification (send_multicast used the batch API, shut down in 2024)
            response = messaging.send_each_for_multicast(message)
            
            if response.failure_count == 0:
                logger.info(f"Successfully sent notification to {response.success_count} device(s)")
                return True
            else:
                logger.warning(
                    f"Partial notification delivery: "
                    f"Success: {response.success_count}, "
                    f"Failure: {response.failure_count}"
                )
                
                # Log failed tokens
                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        logger.error(f"Failed to send to token {tokens[idx]}: {resp.exception}")
                
                return response.success_count > 0
        
        except Exception as e:
            logger.error(f"Error sending FCM notification: {str(e)}")
            return False
    
    def send_report_notification(self, report_data: Dict) -> bool:
        """
        Send formatted stock report as notification
        
        Args:
            report_data: Dictionary containing report information
        
        Returns:
            bool: True if notification sent successfully
        """
        try:
            # Extract summary from report
            title = report_data.get('title', '📈 Daily Stock Report')
            summary = report_data.get('summary', 'Your daily stock report is ready')
            
            # Create preview of report
            body = f"{summary}\n\n"
            
            # Add all insights (the notification is the only place the report is delivered)
            for insight in report_data.get('insights', []):
                body += f"• {insight}\n"

            # Prepare data payload
            data = {
                'report_timestamp': report_data.get('timestamp', ''),
                'stocks_count': str(report_data.get('stocks_count', 0))
            }
            
            # Send notification
            return self.send_notification(title, body, data, link=_build_report_link(report_data))
        
        except Exception as e:
            logger.error(f"Error sending report notification: {str(e)}")
            return False
    
    def add_device_token(self, token: str) -> None:
        """
        Add a new device token
        
        Args:
            token: FCM device token
        """
        if token not in self.device_tokens:
            self.device_tokens.append(token)
            logger.info(f"Added device token: {token[:20]}...")
    
    def remove_device_token(self, token: str) -> None:
        """
        Remove a device token
        
        Args:
            token: FCM device token
        """
        if token in self.device_tokens:
            self.device_tokens.remove(token)
            logger.info(f"Removed device token: {token[:20]}...")


# Global notifier instance
_notifier = None


def get_notifier() -> FCMNotifier:
    """Get or create FCM notifier instance"""
    global _notifier
    if _notifier is None:
        _notifier = FCMNotifier()
    return _notifier


def send_notification(
    title: str,
    body: str,
    data: Optional[Dict] = None
) -> bool:
    """
    Convenience function to send notification
    
    Args:
        title: Notification title
        body: Notification body
        data: Optional data dictionary
    
    Returns:
        bool: True if sent successfully
    """
    return get_notifier().send_notification(title, body, data)


def send_report(report_data: Dict) -> bool:
    """
    Convenience function to send report notification
    
    Args:
        report_data: Report dictionary
    
    Returns:
        bool: True if sent successfully
    """
    return get_notifier().send_report_notification(report_data)