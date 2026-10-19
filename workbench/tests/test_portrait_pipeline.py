import asyncio
import pytest

pytest.importorskip("langchain")

from PIL import Image

from interfaces.image_output import ImageOutput
from pipelines.script2video_pipeline import Script2VideoPipeline


def test_upstream_pipeline_propagates_portrait_size_and_allows_portrait(tmp_path):
    class ImageBackend:
        async def generate_single_image(self, **kwargs):
            assert kwargs["size"] == "720x1280"
            assert kwargs["allow_portrait"] is True
            return ImageOutput(fmt="pil", ext="png", data=Image.new("RGB", (720, 1280)))
    pipeline = Script2VideoPipeline(object(), ImageBackend(), object(), str(tmp_path),
                                    num_image_candidates=1, frame_size="720x1280")
    result = asyncio.run(pipeline.generate_and_select_best_image(prompt="portrait frame", reference_image_paths=[],
        reference_image_path_and_text_pairs=[], target_description="portrait", size=pipeline.frame_size))
    result.save(str(tmp_path / "portrait.png"))
    assert Image.open(tmp_path / "portrait.png").size == (720, 1280)
