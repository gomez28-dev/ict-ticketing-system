import json
import base64
import logging
from django.conf import settings

try:
    import google.generativeai as genai
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

if genai:
    genai.configure(api_key=settings.GEMINI_API_KEY)

def analyze_jrf_image(image_data):
    """
    Analyze a base64-encoded JRF image using Gemini generative model.
    Cycles through candidate models to ensure the scanner never crashes
    if a specific model tier is unavailable.
    Returns a parsed JSON dict on success, or {'error': ...} on failure.
    """
    # A local OpenCV fallback could be added here later if needed.

    if genai is None:
        logger.error("google.generativeai client not installed or import failed.")
        return {"error": "Generative AI client not available on server"}

    try:
        # Strip data URI if present from the frontend camera
        if ',' in image_data:
            image_data = image_data.split(',', 1)[1]

        image_bytes = base64.b64decode(image_data)
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}

        prompt = (
            "You are a strict data extraction assistant. Analyze this scanned Job Request Form. "
            "1. Find the 'Ticket ID' text (usually starts with TKT-). "
            "2. Look at the Performance Indicator table. Tell me which number (1 to 5) is shaded "
            "or marked for 'Quality', 'Efficiency', and 'Timeliness'. Return ONLY a raw JSON object. "
            "The keys must be exact: {\"ticket_id\": \"...\", \"quality\": X, \"efficiency\": X, \"timeliness\": X}"
        )

        # Prioritize the fastest, most capable multimodal flash models available
        candidate_models = [
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-flash-latest',
        ]

        last_error = None

        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [prompt, image_part],
                    generation_config={"response_mime_type": "application/json"}
                )

                # Extract text robustly depending on client version
                raw_text = None
                if hasattr(response, "text") and response.text:
                    raw_text = response.text.strip()
                elif hasattr(response, "output") and response.output:
                    try:
                        raw_text = response.output[0].content[0].text
                    except Exception:
                        raw_text = json.dumps(response.output)
                else:
                    raw_text = str(response)

                # Strip markdown fences if Gemini added them
                if isinstance(raw_text, str):
                    raw_text = raw_text.strip()
                    if raw_text.startswith("```json") and raw_text.endswith("```"):
                        raw_text = raw_text[len("```json"):-len("```")].strip()

                # Parse JSON
                try:
                    parsed = json.loads(raw_text)
                    logger.info("Gemini OMR success with model: %s", model_name)
                    return parsed
                except json.JSONDecodeError:
                    logger.warning("Model %s returned unparseable JSON: %s", model_name, raw_text)
                    last_error = f"Invalid JSON from {model_name}"
                    continue

            except Exception as model_err:
                logger.warning("Model %s failed: %s", model_name, model_err)
                last_error = str(model_err)
                continue

        # All candidate models exhausted
        logger.error("All Gemini candidate models failed. Last error: %s", last_error)
        return {"error": f"All AI models failed. Last error: {last_error}"}

    except Exception as exc:
        logger.exception("Gemini OMR analysis error")
        return {"error": str(exc)}
