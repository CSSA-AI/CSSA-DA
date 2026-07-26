import os
import pytest

@pytest.fixture(autouse=True)
def inject_dummy_env_vars():
    """
    Automatically injects dummy environment variables before every test.
    This prevents the OpenAI SDK from crashing during client initialization.
    """
    # Set a fake API key so the OpenAI client initializes without throwing an error
    os.environ["OPENAI_API_KEY"] = "sk-fake-test-key-do-not-use"
    os.environ["WECHAT_API_KEY"] = "fake-wechat-test-key-do-not-use"
    
    yield # Let the tests run

    # (Optional) Clean up after tests are done
    if "OPENAI_API_KEY" in os.environ:
        del os.environ["OPENAI_API_KEY"]
    if "WECHAT_API_KEY" in os.environ:
        del os.environ["WECHAT_API_KEY"]


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset slowapi's in-memory limiter around every test.

    TestClient always uses the same synthetic client address, so without a
    reset the /chat rate-limit counter accumulates across unrelated tests and
    test order starts to matter.
    """
    from app.core.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
