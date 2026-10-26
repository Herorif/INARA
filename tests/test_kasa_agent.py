"""
Tests for Kasa Smart Home Agent.
Uses REAL devices from settings.json.
"""
import pytest

# Try to import the agent, skip all tests if dependencies missing
try:
    from kasa_agent import KasaAgent
    HAS_KASA = True
except ImportError as e:
    HAS_KASA = False
    IMPORT_ERROR = str(e)

pytestmark = pytest.mark.skipif(not HAS_KASA, reason=f"Kasa dependencies not installed: {IMPORT_ERROR if not HAS_KASA else ''}")



class FakeKasaDevice:
    """Stands in for a python-kasa device; records the calls made to it."""

    def __init__(self, alias, is_on=False):
        self.alias, self.model, self.is_on = alias, "HS103", is_on
        self.is_plug = True
        self.calls = []

    async def update(self):
        self.calls.append("update")

    async def turn_on(self):
        self.calls.append("turn_on")
        self.is_on = True

    async def disconnect(self):
        self.calls.append("disconnect")


class FakeDiscover:
    def __init__(self, devices):
        self.devices = devices
        self.single_lookups = []

    async def discover_single(self, ip):
        self.single_lookups.append(ip)
        return self.devices.get(ip)


class TestKasaAgentOffline:
    """Behaviour with a fake SDK: no network, no real devices."""

    async def test_known_devices_are_seeded_then_initialized(self):
        desk = FakeKasaDevice("Desk Lamp")
        discover = FakeDiscover({"192.168.1.20": desk})
        agent = KasaAgent(
            known_devices=[
                {"ip": "192.168.1.20", "alias": "Desk Lamp"},
                {"ip": "192.168.1.21", "alias": "Offline Plug"},
                {"alias": "missing ip"},
                {"ip": "not-an-ip"},
            ],
            discover_factory=lambda: discover,
        )

        # Only valid known devices are seeded, as offline, with nothing contacted yet.
        assert {item["ip"]: item["online"] for item in agent.snapshot()} == {
            "192.168.1.20": False, "192.168.1.21": False}
        assert agent.devices == {}
        assert discover.single_lookups == []

        await agent.initialize()

        assert discover.single_lookups == ["192.168.1.20", "192.168.1.21"]
        assert agent.devices == {"192.168.1.20": desk}
        states = {item["ip"]: item for item in agent.snapshot()}
        assert states["192.168.1.20"]["online"] is True
        assert states["192.168.1.20"]["type"] == "plug"
        assert states["192.168.1.21"]["online"] is False
        assert agent.get_device_by_alias("desk lamp") is desk

        assert await agent.turn_on("Desk Lamp") is True
        assert desk.is_on is True
        assert "turn_on" in desk.calls
        assert await agent.turn_on("192.168.1.99") is False  # never discovers during control


@pytest.mark.live_hardware
class TestKasaDiscovery:
    """Tests for device discovery."""
    
    @pytest.mark.asyncio
    async def test_initialize_known_devices(self, kasa_devices):
        """Test initializing devices from settings."""
        agent = KasaAgent(known_devices=kasa_devices)
        await agent.initialize()
        print(f"Initialized {len(agent.devices)} devices")
        
        # If we have known devices, they should be loaded
        if kasa_devices:
            assert len(agent.devices) > 0
    
    @pytest.mark.asyncio
    async def test_discover_devices(self):
        """Test discovering devices on network."""
        agent = KasaAgent()
        devices = await agent.discover_devices()
        
        print(f"Discovered {len(devices)} devices:")
        for device in devices:
            print(f"  - {device.get('alias', 'unknown')} @ {device.get('ip', 'unknown')}")
        
        # Discovery should return a list (may be empty if no devices)
        assert isinstance(devices, list)


@pytest.mark.live_hardware
class TestKasaDeviceControl:
    """Tests for device control - only runs if devices exist."""
    
    @pytest.fixture
    async def agent_with_devices(self, kasa_devices):
        """Get an initialized agent with devices."""
        agent = KasaAgent(known_devices=kasa_devices)
        await agent.initialize()
        return agent
    
    @pytest.mark.asyncio
    async def test_get_device_by_alias(self, agent_with_devices, kasa_devices):
        """Test finding device by alias."""
        agent = agent_with_devices
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured in settings.json")
        
        # Try to find first configured device by alias
        device_config = kasa_devices[0]
        if not device_config:
             pytest.skip("Invalid device config (None)")

        alias = device_config.get('alias')
        if alias:
            device = agent.get_device_by_alias(alias)
            print(f"Found device by alias '{alias}': {device}")
    
    @pytest.mark.asyncio  
    async def test_turn_on_device(self, agent_with_devices, kasa_devices):
        """Test turning on a device."""
        agent = agent_with_devices
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        device_config = kasa_devices[0]
        if not device_config:
             pytest.skip("Invalid device config")

        ip = device_config.get('ip')
        if ip:
            result = await agent.turn_on(ip)
            print(f"Turn on result for {ip}: {result}")
            assert result is True
    
    @pytest.mark.asyncio
    async def test_turn_off_device(self, agent_with_devices, kasa_devices):
        """Test turning off a device."""
        agent = agent_with_devices
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        device_config = kasa_devices[0]
        if not device_config:
             pytest.skip("Invalid device config")

        ip = device_config.get('ip')
        if ip:
            result = await agent.turn_off(ip)
            print(f"Turn off result for {ip}: {result}")
            assert result is True
    
    @pytest.mark.asyncio
    async def test_set_brightness(self, agent_with_devices, kasa_devices):
        """Test setting brightness."""
        agent = agent_with_devices
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        device_config = kasa_devices[0]
        if not device_config:
             pytest.skip("Invalid device config")

        ip = device_config.get('ip')
        if ip:
            result = await agent.set_brightness(ip, 50)
            print(f"Set brightness result for {ip}: {result}")
    
    @pytest.mark.asyncio
    async def test_set_color(self, agent_with_devices, kasa_devices):
        """Test setting color."""
        agent = agent_with_devices
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        if not kasa_devices:
            pytest.skip("No Kasa devices configured")
        
        device_config = kasa_devices[0]
        if not device_config:
             pytest.skip("Invalid device config")

        ip = device_config.get('ip')
        if ip:
            result = await agent.set_color(ip, "blue")
            print(f"Set color result for {ip}: {result}")


class TestKasaColorConversion:
    """Test color name to HSV conversion."""
    
    def test_name_to_hsv_red(self):
        """Test red color conversion."""
        agent = KasaAgent()
        hsv = agent.name_to_hsv("red")
        assert hsv is not None
        assert hsv[0] == 0  # Hue for red
    
    def test_name_to_hsv_blue(self):
        """Test blue color conversion."""
        agent = KasaAgent()
        hsv = agent.name_to_hsv("blue")
        assert hsv is not None
        assert hsv[0] == 240  # Hue for blue
    
    def test_name_to_hsv_unknown(self):
        """Test unknown color returns None."""
        agent = KasaAgent()
        hsv = agent.name_to_hsv("notacolor")
        assert hsv is None
