"""Regression test for ViewImageMiddleware content block format.

Ensures the empty-images fallback returns structured content blocks
(list of dicts) rather than a plain string list, which would cause
OpenAI-compatible APIs to reject the request with 400 BadRequest.
"""

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware


class TestCreateImageDetailsMessageFallback:
    def test_empty_viewed_images_returns_structured_content_blocks(self):
        """Fallback must produce list[dict] with 'type' key, not list[str]."""
        middleware = ViewImageMiddleware()
        result = middleware._create_image_details_message({"viewed_images": {}})

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict), "content block must be dict, not str"
        assert result[0]["type"] == "text"
