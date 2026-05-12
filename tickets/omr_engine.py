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

# A local OpenCV fallback could be added here later if needed.

def analyze_jrf_image(image_data):
    """
    Analyze a base64-encoded JRF image using Gemini generative model.
    Cycles through candidate models until one succeeds.
    Returns a parsed JSON dict on success, or {'error': ..., 'raw': ...} on failure.
    """
    if genai is None:
        logger.error("google.generativeai client not installed or import failed.")
        return {"error": "Generative AI client not available on server"}

    try:
        # Strip data URI prefix if present from the frontend camera
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

        # Prioritize the fastest, most capable multimodal flash models.
        # The loop tries each in order and falls back if a model is unavailable.
        candidate_models = [
            'gemini-2.5-flash-preview-05-20',
            'gemini-2.0-flash',
            'gemini-1.5-flash',
        ]

        last_error = None

        for model_name in candidate_models:
            try:
                logger.debug("Attempting Gemini model: %s", model_name)
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [prompt, image_part],
                    generation_config={"response_mime_type": "application/json"}
                )

                # Debug: log raw response for troubleshooting (no secrets logged)
                try:
                    logger.debug("Gemini raw response (%s): %s", model_name, getattr(response, "__dict__", str(response)))
                except Exception:
                    logger.debug("Gemini raw response (str): %s", str(response))

                # Extract text robustly across different client versions
                raw_text = None
                if hasattr(response, "text") and response.text:
                    raw_text = response.text.strip()
                elif hasattr(response, "output") and response.output:
                    # Some client versions nest the textual output
                    try:
                        raw_text = response.output[0].content[0].text
                    except Exception:
                        raw_text = json.dumps(response.output)
                else:
                    raw_text = str(response)

                # Strip Markdown fences if Gemini added them despite the mime type config
                if isinstance(raw_text, str):
                    raw_text = raw_text.strip()
                    if raw_text.startswith("```json") and raw_text.endswith("```"):
                        raw_text = raw_text[len("```json"):-len("```")].strip()
                    elif raw_text.startswith("```") and raw_text.endswith("```"):
                        raw_text = raw_text[3:-3].strip()

                # Attempt JSON parse
                try:
                    parsed = json.loads(raw_text)
                    logger.info("OMR extraction succeeded using model: %s", model_name)
                    return parsed
                except Exception:
                    logger.error("Failed to parse JSON from model %s. Raw: %s", model_name, raw_text)
                    return {"error": "Invalid JSON returned from Gemini", "raw": raw_text}

            except Exception as model_exc:
                logger.warning("Model %s failed: %s — trying next model.", model_name, model_exc)
                last_error = model_exc
                continue  # Try the next candidate

        # All models exhausted
        logger.error("All Gemini candidate models failed. Last error: %s", last_error)
        return {"error": f"All AI models failed. Last error: {last_error}"}

    except Exception as exc:
        logger.exception("Gemini OMR analysis error")
        return {"error": str(exc)}
