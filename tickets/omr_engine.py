import json
import base64
import google.generativeai as genai
from django.conf import settings


genai.configure(api_key=settings.GEMINI_API_KEY)


def analyze_jrf_image(image_data):
    try:
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)
        image_parts = [{"mime_type": "image/jpeg", "data": image_bytes}]

        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = (
            "You are a strict data extraction assistant. Analyze this scanned Job Request Form. "
            "1. Find the 'Ticket ID' text (usually starts with TKT-). "
            "2. Look at the Performance Indicator table. Tell me which number (1 to 5) is shaded "
            "or marked for 'Quality', 'Efficiency', and 'Timeliness'. Return ONLY a raw JSON object. "
            "The keys must be exact: {\"ticket_id\": \"...\", \"quality\": X, \"efficiency\": X, \"timeliness\": X}"
        )

        response = model.generate_content(
            [prompt, image_parts[0]],
            generation_config={"response_mime_type": "application/json"},
        )

        raw_text = response.text.strip()
        if raw_text.startswith("```json") and raw_text.endswith("```"):
            raw_text = raw_text[len("```json"):-len("```")].strip()

        return json.loads(raw_text)
    except Exception as e:
        print(f"Gemini OMR analysis error: {e}")
        return {"error": str(e)}
