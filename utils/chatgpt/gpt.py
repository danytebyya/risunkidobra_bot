import asyncio
import re, json
import random

from openai import OpenAI

from config import OPENAI_API_KEY


client = OpenAI(api_key=OPENAI_API_KEY)


async def generate_response(category, prompt):
    """
    Генерирует поздравление в заданной тональности category по тексту prompt.
    Возвращает готовый текст (~10 предложений).
    """
    role_prompt = f'''
                    Напиши красивое поздравление в стиле "{category}" на русском языке. Целься на ~10 предложений.
                  '''

    system_message = {"role": "system", "content": role_prompt}

    prompt = {"role": "system", "content": f"Пожелания при создании: {prompt}"}

    messages = [system_message, prompt]

    model = "gpt-4o-mini"

    response = await asyncio.to_thread(
        client.chat.completions.create,
        messages=messages,
        model=model,
        temperature=0.7,
        max_tokens=1600,
        timeout=60
    )
    answer = response.choices[0].message.content

    return answer


async def generate_response_with_edits(category, base_prompt, edits):
    """
    category      — тональность
    base_prompt   — исходный запрос пользователя
    edits         — список строк с пожеланиями правок
    """
    edit_instructions = "\n".join(f"{i+1}. {e}" for i, e in enumerate(edits))
    system = {"role": "system", "content":
        f'Ты — генератор поздравлений в стиле "{category}". ' 
        f'У тебя есть базовый запрос: "{base_prompt}".\n'
        f'Пользователь просит следующие правки:\n{edit_instructions}\n'
        'Сформируй обновлённый вариант (~10 предложений).'
    }
    messages = [system]
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=1600,
        timeout=60
    )
    return response.choices[0].message.content


async def generate_daily_quote_model() -> dict:
    """
    Запрашивает у модели одну короткую вдохновляющую цитату и источник.
    Модель обязана вернуть JSON с полями:
      - quote (строка)
      - source (строка или пустая)
    При невалидном JSON возвращается fallback: весь ответ - quote, source=None.
    """
    system_msg = {
        "role": "system",
        "content": (
            "Ты — генератор коротких тёплых вдохновляющих цитат. "
            "Отвечай строго JSON-объектом с полями \"quote\" и \"source\". "
            "Если цитата твоего собственного сочинения, оставляй source пустым."
        )
    }
    if random.random() < 0.5:
        user_content = "Сгенерируй одну короткую тёплую цитату собственного сочинения."
    else:
        user_content = (
            "Приведи одну короткую тёплую вдохновляющую цитату из книги, фильма или сериала, "
            "и обязательно укажи её источник."
        )

    user_msg = {"role": "user", "content": user_content}

    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=[system_msg, user_msg],
        temperature=0.8,
        max_tokens=100,
        timeout=30
    )
    raw = resp.choices[0].message.content.strip()
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", raw, re.DOTALL)
    blob = (m.group(1) if m else raw).strip("` \n")

    try:
        data = json.loads(blob)
        quote = data.get("quote", "").strip("` \n")
        source = data.get("source", "").strip("` \n") or None
    except json.JSONDecodeError:
        quote = raw.strip("` \n")
        source = None

    return {"quote": quote, "source": source}
