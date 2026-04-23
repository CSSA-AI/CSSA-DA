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
    
    yield # Let the tests run
    
    # (Optional) Clean up after tests are done
    if "OPENAI_API_KEY" in os.environ:
        del os.environ["OPENAI_API_KEY"]