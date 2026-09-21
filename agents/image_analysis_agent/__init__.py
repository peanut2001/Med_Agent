import logging
import os
from threading import Lock

from .image_classifier import ImageClassifier
from .chest_xray_agent.covid_chest_xray_inference import ChestXRayClassification
# from .brain_tumor_agent.brain_tumor_inference import BrainTumorAgent
from .skin_lesion_agent.skin_lesion_inference import SkinLesionSegmentation
from agents.concurrency import run_image_inference

logger = logging.getLogger(__name__)


class ImageModelUnavailableError(RuntimeError):
    """Raised when a local CV model cannot be loaded.

    Callers turn this into a user-facing "analysis unavailable" answer instead
    of failing the whole request, mirroring the brain tumor agent.
    """


class ImageAnalysisAgent:
    """
    Agent responsible for processing image uploads and classifying them as medical or non-medical, and determining their type.

    The two torch models are loaded lazily on first use. Loading them at import
    time made a fresh deployment unable to start at all: the skin lesion
    checkpoint is gitignored, so a clean clone downloads 183 MB from Google
    Drive during import, and any failure there propagated out of `import`.
    """

    def __init__(self, config):
        self._config = config
        self.image_classifier = ImageClassifier(vision_model=config.medical_cv.llm)
        self._chest_xray_agent = None
        self._skin_lesion_agent = None
        self._load_lock = Lock()

    def _load_once(self, attribute: str, label: str, factory):
        """Build a model once, serializing concurrent first-use callers."""
        existing = getattr(self, attribute)
        if existing is not None:
            return existing
        with self._load_lock:
            existing = getattr(self, attribute)
            if existing is not None:
                return existing
            try:
                model = factory()
            except Exception as exc:
                # Do not cache the failure: a later request can succeed once the
                # checkpoint is placed on disk, without restarting the app.
                logger.error("%s model unavailable: %s", label, exc)
                raise ImageModelUnavailableError(label) from exc
            setattr(self, attribute, model)
            return model

    @property
    def chest_xray_agent(self):
        return self._load_once(
            "_chest_xray_agent",
            "chest_xray",
            lambda: ChestXRayClassification(
                model_path=self._config.medical_cv.chest_xray_model_path
            ),
        )

    @property
    def skin_lesion_agent(self):
        return self._load_once(
            "_skin_lesion_agent",
            "skin_lesion",
            lambda: SkinLesionSegmentation(
                model_path=self._config.medical_cv.skin_lesion_model_path
            ),
        )

    # classify image
    def analyze_image(self, image_path: str) -> str:
        """Classifies images as medical or non-medical and determines their type."""
        return run_image_inference(self.image_classifier.classify_image, image_path)

    # chest x-ray agent
    def classify_chest_xray(self, image_path: str) -> str:
        agent = self.chest_xray_agent
        return run_image_inference(agent.predict, image_path)

    # # brain tumor agent
    # def classify_brain_tumor(self, image_path: str) -> str:
    #     return self.brain_tumor_agent.predict(image_path)

    # skin lesion agent
    def segment_skin_lesion(self, image_path: str, output_path: str) -> str:
        agent = self.skin_lesion_agent
        return run_image_inference(agent.predict, image_path, output_path)
