from yookassa import Configuration, Payment
import uuid
import config

# Configuration.account_id = "1025133"
# Configuration.secret_key = config.PAYMENT_SECRET_KEY


Configuration.account_id = "1029197"
Configuration.secret_key = config.PAYMENT_SECRET_KEY_LIVE


async def create_payment(user_id, value, description: str = "Оплата за открытку без водяного знака"):
    idempotence_key = str(uuid.uuid4())

    payment = Payment.create({
        "amount": {
            "value": value,
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/risunkidobra_bot"
        },
        "capture": True,
        "description": description,
        "receipt": {
            "customer": {
                "email": f"user_{user_id}@example.com"
            },
            "items": [
                {
                    "description": description,
                    "quantity": "1",
                    "amount": {
                        "value": value,
                        "currency": "RUB"
                    },
                    "payment_subject": "commodity",
                    "payment_mode": "full_payment",
                    "vat_code": "1"
                }
            ]
        }
    }, idempotence_key)

    confirmation_url = None
    payment_id = None
    if payment is not None:
        confirmation = getattr(payment, 'confirmation', None)
        if confirmation is not None:
            confirmation_url = getattr(confirmation, 'confirmation_url', None)
        if hasattr(payment, 'id'):
            payment_id = payment.id
        # Альтернативно, если payment поддерживает []
        if not confirmation_url and isinstance(payment, dict):
            confirmation_url = payment.get('confirmation', {}).get('confirmation_url')
            payment_id = payment.get('id')

    print("link:", confirmation_url)
    # Возвращаем URL для подтверждения платежа
    return confirmation_url, payment_id


async def check_payment_status(payment_id):
    payment = Payment.find_one(payment_id)
    return payment.status
