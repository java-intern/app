import logging
import httpx
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    async def send_verification_email(recipient_email: str, recipient_name: str | None, otp_code: str) -> bool:
        """
        Dispatches a 6-digit verification code to the recipient via Brevo REST API v3.
        If BREVO_API_KEY is configured, sends real transactional email.
        If Brevo fails, throws an explicit exception detailing why Brevo rejected delivery.
        """
        api_key = (settings.BREVO_API_KEY or "").strip().strip('"').strip("'")
        sender_email = (settings.BREVO_SENDER_EMAIL or "yoganandatamm@gmail.com").strip().strip('"').strip("'")
        sender_name = (settings.BREVO_SENDER_NAME or "AdaptiveTrust Security").strip().strip('"').strip("'")

        if api_key:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json"
            }

            display_name = recipient_name or recipient_email
            payload = {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": recipient_email.strip(), "name": display_name}],
                "subject": f"AdaptiveTrust - Your Verification Code is {otp_code}",
                "textContent": f"Hello {display_name},\n\nYour 6-digit verification code is: {otp_code}\n\nThis code will expire in 15 minutes.",
                "htmlContent": f"""
                <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #0f172a; color: #f8fafc; padding: 32px; border-radius: 12px;">
                    <div style="text-align: center; margin-bottom: 24px;">
                        <h2 style="color: #6366f1; margin: 0; font-size: 24px;">AdaptiveTrust Security</h2>
                        <p style="color: #94a3b8; font-size: 14px;">Email Verification Request</p>
                    </div>
                    <div style="background: rgba(30, 41, 59, 0.8); padding: 24px; border-radius: 8px; border: 1px solid #334155; text-align: center;">
                        <p style="font-size: 16px; margin-bottom: 16px;">Hello {display_name},</p>
                        <p style="color: #94a3b8; font-size: 14px; margin-bottom: 24px;">Use the following 6-digit verification code to complete your registration or login:</p>
                        <div style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #38bdf8; background: #0284c71a; padding: 16px; border-radius: 8px; display: inline-block;">
                            {otp_code}
                        </div>
                        <p style="color: #64748b; font-size: 12px; margin-top: 24px;">This code will expire in 15 minutes. If you did not request this code, please ignore this email.</p>
                    </div>
                </div>
                """
            }

            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code in (200, 201, 202):
                        logger.info(f"Verification email successfully delivered via Brevo to {recipient_email}")
                        print(f"\n[BREVO EMAIL DELIVERED SUCCESS] Sent OTP {otp_code} to {recipient_email}\n")
                        return True
                    else:
                        error_text = res.text
                        logger.error(f"Brevo API error ({res.status_code}): {error_text}")
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Brevo Email Delivery Failed ({res.status_code}): {error_text}"
                        )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Network error dispatching Brevo email to {recipient_email}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Email dispatch network error: {str(e)}"
                )
        else:
            # Dev Fallback Mode when BREVO_API_KEY is not configured
            logger.info(f"[DEV EMAIL SERVICE] OTP for {recipient_email}: {otp_code}")
            print(f"\n=======================================================")
            print(f" [DEV EMAIL SERVICE] VERIFICATION EMAIL TO: {recipient_email}")
            print(f" [DEV EMAIL SERVICE] OTP CODE: {otp_code}")
            print(f"=======================================================\n")
            return True
