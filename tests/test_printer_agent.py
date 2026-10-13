"""
Tests for 3D Printer Agent.
Discovery only - no actual print jobs.
"""
import pytest
import asyncio

# Try to import the agent, skip all tests if dependencies missing
try:
    from printer_agent import PrinterAgent, PrinterType, Printer
    HAS_PRINTER = True
except ImportError as e:
    HAS_PRINTER = False
    IMPORT_ERROR = str(e)
    # Define stubs to prevent NameError
    PrinterAgent = None
    PrinterType = None
    Printer = None

pytestmark = pytest.mark.skipif(not HAS_PRINTER, reason=f"Printer dependencies not installed: {IMPORT_ERROR if not HAS_PRINTER else ''}")



class TestPrinterAgentInit:
    """Test PrinterAgent initialization."""
    
    def test_agent_creation(self):
        """Test PrinterAgent can be created."""
        agent = PrinterAgent()
        assert agent is not None
        assert hasattr(agent, 'printers')
        assert hasattr(agent, 'slicer_path')
    
    def test_slicer_detection(self):
        """Test OrcaSlicer/PrusaSlicer detection."""
        agent = PrinterAgent()
        slicer_path = agent.slicer_path
        
        if slicer_path:
            print(f"Found slicer at: {slicer_path}")
            assert agent.slicer_path.exists() or str(slicer_path).endswith('.exe')
        else:
            print("No slicer detected (OrcaSlicer/PrusaSlicer not installed)")
    
    def test_orca_profiles_detection(self):
        """Test OrcaSlicer profiles directory detection."""
        agent = PrinterAgent()
        
        if agent._orca_profiles_dir:
            print(f"OrcaSlicer profiles at: {agent._orca_profiles_dir}")
        else:
            print("OrcaSlicer profiles directory not found")


class TestPrinterDiscovery:
    """Test printer discovery (mDNS)."""
    
    @pytest.mark.asyncio
    async def test_discover_printers(self):
        """Test discovering printers on network."""
        agent = PrinterAgent()
        printers = await agent.discover_printers(timeout=3.0)
        
        print(f"Discovered {len(printers)} printers:")
        for printer in printers:
            print(f"  - {printer.get('name', 'unknown')} @ {printer.get('host', 'unknown')}")
            print(f"    Type: {printer.get('printer_type', 'unknown')}")
        
        assert isinstance(printers, list)
    
    def test_add_printer_manually(self):
        """Test manually adding a printer."""
        agent = PrinterAgent()
        
        agent.add_printer_manually(
            name="Test Printer",
            host="192.168.1.100",
            port=80,
            printer_type="octoprint"
        )
        
        assert "192.168.1.100" in agent.printers
        printer = agent.printers["192.168.1.100"]
        assert printer.name == "Test Printer"
        print(f"Added printer: {printer.name}")


class TestPrinterWithSettings:
    """Test with printers from settings.json."""
    
    @pytest.fixture
    def agent_with_settings(self, printers):
        """Create agent and load printers from settings."""
        agent = PrinterAgent()
        
        for p in printers:
            agent.add_printer_manually(
                name=p.get('name', 'Unknown'),
                host=p.get('host'),
                port=p.get('port', 80),
                printer_type=p.get('type', 'octoprint'),
                api_key=p.get('api_key')
            )
        
        return agent
    
    def test_load_printers_from_settings(self, agent_with_settings, printers):
        """Test loading printers from settings."""
        agent = agent_with_settings
        
        print(f"Loaded {len(agent.printers)} printers from settings")
        for host, printer in agent.printers.items():
            print(f"  - {printer.name} @ {host} ({printer.printer_type})")
        
        if printers:
            assert len(agent.printers) == len(printers)
    
    def test_resolve_printer_by_name(self, agent_with_settings, printers):
        """Test resolving printer by name."""
        agent = agent_with_settings
        
        if not printers:
            pytest.skip("No printers in settings.json")
        
        name = printers[0].get('name')
        if name:
            printer = agent._resolve_printer(name)
            if printer:
                print(f"Resolved '{name}' to {printer.host}")
    
    def test_resolve_printer_by_host(self, agent_with_settings, printers):
        """Test resolving printer by host/IP."""
        agent = agent_with_settings
        
        if not printers:
            pytest.skip("No printers in settings.json")
        
        host = printers[0].get('host')
        if host:
            printer = agent._resolve_printer(host)
            if printer:
                print(f"Resolved host '{host}' to {printer.name}")
                assert printer.host == host


class TestPrinterStatus:
    """Test printer status queries (requires connected printer)."""
    
    @pytest.mark.asyncio
    async def test_get_print_status(self, printers):
        """Test getting print status from a printer."""
        if not printers:
            pytest.skip("No printers configured")
        
        agent = PrinterAgent()
        
        # Add first printer from settings
        p = printers[0]
        agent.add_printer_manually(
            name=p.get('name', 'Unknown'),
            host=p.get('host'),
            port=p.get('port', 80),
            printer_type=p.get('type', 'octoprint'),
            api_key=p.get('api_key')
        )
        
        try:
            status = await agent.get_print_status(p.get('host'))
            print(f"Printer status: {status}")
        except Exception as e:
            print(f"Could not get status (printer may be offline): {e}")


class TestSlicerProfiles:
    """Test slicer profile detection."""
    
    def test_get_available_profiles(self):
        """Test getting available slicer profiles."""
        agent = PrinterAgent()
        profiles = agent.get_available_profiles()
        
        print(f"Found profiles:")
        print(f"  Machines: {len(profiles.get('machines', []))}")
        print(f"  Processes: {len(profiles.get('processes', []))}")
        print(f"  Filaments: {len(profiles.get('filaments', []))}")
        
        assert isinstance(profiles, dict)
    
    def test_find_matching_profile(self, printers):
        """Test finding matching profile for a printer."""
        if not printers:
            pytest.skip("No printers configured")
        
        agent = PrinterAgent()
        printer_name = printers[0].get('name', '')
        
        # Try to find matching profiles
        profiles = agent.get_profiles_for_printer(printer_name)
        print(f"Profiles for '{printer_name}':")
        for key, path in profiles.items():
            if path:
                print(f"  {key}: {path}")


class TestPrinterType:
    """Test PrinterType enum."""
    
    def test_printer_types_exist(self):
        """Test all printer types are defined."""
        assert PrinterType.OCTOPRINT.value == "octoprint"
        assert PrinterType.MOONRAKER.value == "moonraker"
        assert PrinterType.PRUSALINK.value == "prusalink"
        assert PrinterType.UNKNOWN.value == "unknown"


class TestPrinterDataclass:
    """Test Printer dataclass."""
    
    def test_printer_creation(self):
        """Test creating a Printer object."""
        printer = Printer(
            name="Test",
            host="192.168.1.1",
            port=80,
            printer_type=PrinterType.OCTOPRINT
        )
        
        assert printer.name == "Test"
        assert printer.host == "192.168.1.1"
        assert printer.port == 80
    
    def test_printer_to_dict(self):
        """Test Printer.to_dict() method."""
        printer = Printer(
            name="Test",
            host="192.168.1.1",
            port=80,
            printer_type=PrinterType.MOONRAKER
        )
        
        d = printer.to_dict()
        assert d['name'] == "Test"
        assert d['host'] == "192.168.1.1"
        assert 'printer_type' in d
