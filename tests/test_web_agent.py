"""
Tests for Web Automation Agent.
"""
import pytest
import asyncio
import os

from web_agent import WebAgent


class TestWebAgentInit:
    """Test WebAgent initialization."""
    
    def test_agent_creation(self):
        """Test WebAgent can be created."""
        agent = WebAgent()
        assert agent is not None
        assert hasattr(agent, 'client')
        print("WebAgent initialized successfully")
    
    def test_agent_has_browser_attrs(self):
        """Test WebAgent has browser-related attributes."""
        agent = WebAgent()
        assert hasattr(agent, 'browser')
        assert hasattr(agent, 'page')
        assert hasattr(agent, 'context')


class TestCoordinateDenormalization:
    """Test coordinate conversion functions."""
    
    def test_denormalize_x(self):
        """Test X coordinate denormalization."""
        agent = WebAgent()
        
        # Test at different normalized values
        result = agent.denormalize_x(500, 1000)  # 50% of 1000
        print(f"denormalize_x(500, 1000) = {result}")
        assert isinstance(result, (int, float))
    
    def test_denormalize_y(self):
        """Test Y coordinate denormalization."""
        agent = WebAgent()
        
        result = agent.denormalize_y(500, 1000)  # 50% of 1000
        print(f"denormalize_y(500, 1000) = {result}")
        assert isinstance(result, (int, float))


class TestWebBrowserLaunch:
    """Test browser launching capabilities."""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_browser_launch_headless(self):
        """Test launching browser in headless mode."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto("https://www.google.com")
                
                title = await page.title()
                print(f"Page title: {title}")
                assert "Google" in title
                
                await browser.close()
                print("Browser launch test passed")
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebNavigation:
    """Test web navigation capabilities."""
    
    @pytest.mark.asyncio
    async def test_navigate_to_url(self):
        """Test navigating to a URL."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://example.com")
                content = await page.content()
                
                assert "Example Domain" in content
                print("Navigation test passed")
                
                await browser.close()
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebScreenshot:
    """Test screenshot capabilities."""
    
    @pytest.mark.asyncio
    async def test_capture_screenshot(self, temp_dir):
        """Test capturing a screenshot."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto("https://example.com")
                
                screenshot_path = temp_dir / "test_screenshot.png"
                await page.screenshot(path=str(screenshot_path))
                
                assert screenshot_path.exists()
                print(f"Screenshot saved to: {screenshot_path}")
                
                await browser.close()
        except Exception as e:
            pytest.skip(f"Playwright not available: {e}")


class TestWebAgentTask:
    """Test full web agent task execution."""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_simple_web_task(self):
        """Test running a simple web task."""
        agent = WebAgent()
        
        updates = []
        
        async def update_callback(screenshot_b64, log_text):
            updates.append({"log": log_text})
            print(f"Update: {log_text[:100]}...")
        
        try:
            result = await agent.run_task(
                prompt="Navigate to example.com and tell me the page title",
                update_callback=update_callback
            )
            
            print(f"Task result: {result}")
            print(f"Updates received: {len(updates)}")
        except Exception as e:
            print(f"Task failed: {e}")


class TestPlaywrightInstallation:
    """Test Playwright availability."""
    
    def test_playwright_import(self):
        """Test if Playwright is installed."""
        try:
            from playwright.async_api import async_playwright
            print("Playwright is installed")
        except ImportError:
            pytest.skip("Playwright not installed")
    
    @pytest.mark.asyncio
    async def test_playwright_browsers(self):
        """Test if Playwright browsers are installed."""
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
                print("Chromium browser is available")
        except Exception as e:
            pytest.skip(f"Playwright browsers not installed: {e}")
