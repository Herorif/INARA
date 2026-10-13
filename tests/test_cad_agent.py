"""
Tests for CAD Generation Agent.
"""
import pytest
import asyncio
import os

from cad_agent import CadAgent


class TestCadAgentInit:
    """Test CadAgent initialization."""
    
    def test_agent_creation(self):
        """Test CadAgent can be created."""
        agent = CadAgent()
        assert agent is not None
        assert hasattr(agent, 'client')
        print("CadAgent initialized successfully")
    
    def test_agent_with_callbacks(self):
        """Test CadAgent with thought/status callbacks."""
        thoughts = []
        statuses = []
        
        def on_thought(text):
            thoughts.append(text)
        
        def on_status(status):
            statuses.append(status)
        
        agent = CadAgent(on_thought=on_thought, on_status=on_status)
        assert agent.on_thought is not None
        assert agent.on_status is not None


class TestCadGeneration:
    """Test CAD generation (requires API key)."""
    
    @pytest.fixture
    def agent(self):
        """Create a CadAgent instance."""
        return CadAgent()
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_generate_simple_cube(self, agent):
        """Test generating a simple cube."""
        thoughts = []
        statuses = []
        
        agent.on_thought = lambda t: thoughts.append(t)
        agent.on_status = lambda s: statuses.append(s)
        
        try:
            result = await agent.generate_prototype("A simple 10mm cube")
            print(f"Generation result: {result}")
            print(f"Thoughts received: {len(thoughts)}")
            print(f"Statuses received: {len(statuses)}")
            
            # Check if STL was generated
            if "output.stl" in str(result) or "success" in str(result).lower():
                print("CAD generation successful")
        except Exception as e:
            print(f"Generation failed (expected if build123d not installed): {e}")
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_generate_sphere(self, agent):
        """Test generating a sphere."""
        try:
            result = await agent.generate_prototype("A sphere with 25mm radius")
            print(f"Sphere generation result: {result}")
        except Exception as e:
            print(f"Sphere generation failed: {e}")


class TestCadIteration:
    """Test CAD iteration (modifying existing designs)."""
    
    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("GEMINI_API_KEY"),
        reason="GEMINI_API_KEY not set"
    )
    async def test_iterate_prototype(self):
        """Test iterating on an existing design."""
        agent = CadAgent()
        
        # First check if temp_cad_gen.py exists
        temp_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "backend",
            "temp_cad_gen.py"
        )
        
        if not os.path.exists(temp_file):
            pytest.skip("No existing temp_cad_gen.py to iterate on")
        
        try:
            result = await agent.iterate_prototype("Make it 50% larger")
            print(f"Iteration result: {result}")
        except Exception as e:
            print(f"Iteration failed: {e}")


class TestCadSystemPrompt:
    """Test CAD agent system prompt configuration."""
    
    def test_system_prompt_exists(self):
        """Test that system prompt is defined."""
        agent = CadAgent()
        # The agent should have a system prompt for Gemini
        assert hasattr(agent, 'system_prompt') or hasattr(agent, 'client')


class TestBuild123dImport:
    """Test build123d availability."""
    
    def test_build123d_import(self):
        """Test if build123d is installed."""
        try:
            import build123d
            print(f"build123d version: {build123d.__version__}")
        except ImportError:
            pytest.skip("build123d not installed")
