from yookassa import Configuration, Payment
import uuid
import config

Configuration.account_id = "1025133"
Configuration.secret_key = config.PAYMENT_SECRET_KEY


#Configuration.account_id = "1029197"
#Configuration.secret_key = config.PAYMENT_SECRET_KEY_LIVE


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

    print("link:", payment.confirmation.confirmation_url)
    # Возвращаем URL для подтверждения платежа
    return payment['confirmation']['confirmation_url'], payment.id


async def check_payment_status(payment_id):
    payment = Payment.find_one(payment_id)
    return payment.status
