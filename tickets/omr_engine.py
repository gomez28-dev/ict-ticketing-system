import json
import base64
import logging
from django.conf import settings

try:
    import google.generativeai as genai
except Exception:
    genai = None

logger = logging.getLogger(__name__)

if genai:
    genai.configure(api_key=settings.GEMINI_API_KEY)

def analyze_jrf_image(image_data):
    """
    Analyze a base64-encoded JRF image using Gemini generative model.
    Returns a parsed JSON dict on success, or {'error': ..., 'raw': ...} on failure.
    """
    # A local OpenCV fallback could be added here later if needed.
    
    if genai is None:
        logger.error("google.generativeai client not installed or import failed.")
        return {"error": "Generative AI client not available on server"}

    try:
        # Strip data URI if present
        if ',' in image_data:
            image_data = image_data.split(',', 1)[1]

        image_bytes = base64.b64decode(image_data)
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}

        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = (
            "You are a strict data extraction assistant. Analyze this scanned Job Request Form. "
            "1. Find the 'Ticket ID' text (usually starts with TKT-). "
            "2. Look at the Performance Indicator table. Tell me which number (1 to 5) is shaded "
            "or marked for 'Quality', 'Efficiency', and 'Timeliness'. Return ONLY a raw JSON object. "
            "The keys must be exact: {\"ticket_id\": \"...\", \"quality\": X, \"efficiency\": X, \"timeliness\": X}"
        )

        # Call Gemini. Keep generation_config minimal but request JSON mime type
        response = model.generate_content([prompt, image_part], generation_config={"response_mime_type": "application/json"})

        # Debug: log raw response object for troubleshooting (will not log secrets)
        try:
            logger.debug("Gemini raw response: %s", getattr(response, "__dict__", str(response)))
        except Exception:
            logger.debug("Gemini raw response (str): %s", str(response))

        # Extract candidate text values from common fields
        raw_text = None
        if hasattr(response, "text") and response.text:
            raw_text = response.text.strip()
        elif hasattr(response, "output") and response.output:
            # some client versions nest the textual output
            try:
                raw_text = response.output[0].content[0].text
            except Exception:
                raw_text = json.dumps(response.output)
        else:
            raw_text = str(response)

        # Remove markdown fences if present
        if isinstance(raw_text, str):
            raw_text = raw_text.strip()
            if raw_text.startswith("```json") and raw_text.endswith("```"):
                raw_text = raw_text[len("```json"):-len("```")].strip()

        # Try parse JSON
        try:
            parsed = json.loads(raw_text)
            return parsed
        except Exception:
            logger.error("Failed to parse JSON from Gemini response. Raw: %s", raw_text)
            return {"error": "Invalid JSON returned from Gemini", "raw": raw_text}

    except Exception as exc:
        logger.exception("Gemini OMR analysis error")
        return {"error": str(exc)}

