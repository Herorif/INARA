"""
PrinterAgent - Handles 3D printer discovery, slicing, and print job submission.

Supported Printer Types:
- OctoPrint (REST API)
- Moonraker/Klipper (REST API)
- Other protocols remain unavailable; no compatibility fallback is attempted.
"""

import asyncio
import os
import subprocess
import platform
import time
from typing import Dict, List, Optional, Any

from devices.printer_models import PrinterType, Printer, PrintStatus
from devices.printer_protocols import PrinterProtocolClient


class PrinterAgent:
    """
    Handles 3D printer discovery, profile management, slicing, and print job submission.
    """
    
    def __init__(self, profiles_dir: str = "printer_profiles"):
        self.printers: Dict[str, Printer] = {}  # host -> Printer
        self.profiles_dir = profiles_dir
        self.protocol = PrinterProtocolClient()
        self._error_tracker = set() # Track hosts with active errors to prevent log spam
        self._status_failures: Dict[str, int] = {}
        self._next_status_poll_at: Dict[str, float] = {}
        self._last_status: Dict[str, PrintStatus] = {}
        self._online_poll_interval = 5.0
        self._printing_poll_interval = 2.0
        self._offline_backoff_steps = (5.0, 15.0, 30.0, 60.0)
        
        # Detect slicer path and profiles directory
        self.slicer_path = self._detect_slicer_path()
        self._orca_profiles_dir = self._detect_orca_profiles_dir()
        
        # Ensure profiles directory exists
        os.makedirs(profiles_dir, exist_ok=True)

    def get_slicer_status(self) -> Dict[str, Optional[str]]:
        available = bool(self.slicer_path)
        return {
            "available": available,
            "path": self.slicer_path,
            "profiles_dir": self._orca_profiles_dir,
            "message": (
                f"Using slicer at {self.slicer_path}"
                if available
                else "Printing is unavailable until OrcaSlicer or PrusaSlicer is installed."
            ),
        }

    def should_poll_printer(self, host: str) -> bool:
        printer = self._resolve_printer(host)
        if printer and printer.printer_type not in (PrinterType.OCTOPRINT, PrinterType.MOONRAKER):
            return False
        key = self._status_key(printer) if printer else host
        return time.monotonic() >= self._next_status_poll_at.get(key, 0.0)

    def get_printer_list(self) -> List[Dict]:
        printer_list = []
        for host, printer in self.printers.items():
            item = printer.to_dict()
            status = self._last_status.get(self._status_key(printer))
            if status:
                item["status"] = status.to_dict()
            printer_list.append(item)
        return printer_list

    def _set_next_poll(self, host: str, delay: float) -> None:
        printer = self._resolve_printer(host)
        key = self._status_key(printer) if printer else host
        self._next_status_poll_at[key] = time.monotonic() + max(delay, 0.0)

    def _record_status_success(self, printer: Printer, status: PrintStatus) -> PrintStatus:
        self._error_tracker.discard(self._status_key(printer))
        self._status_failures[self._status_key(printer)] = 0
        self._last_status[self._status_key(printer)] = status

        state = (status.state or "").lower()
        poll_delay = self._printing_poll_interval if state in {"printing", "paused"} else self._online_poll_interval
        self._set_next_poll(self._status_key(printer), poll_delay)
        return status

    def _record_status_failure(self, printer: Printer, message: str) -> PrintStatus:
        failures = self._status_failures.get(self._status_key(printer), 0) + 1
        self._status_failures[self._status_key(printer)] = failures

        backoff_index = min(failures - 1, len(self._offline_backoff_steps) - 1)
        self._set_next_poll(self._status_key(printer), self._offline_backoff_steps[backoff_index])

        if self._status_key(printer) not in self._error_tracker:
            print(f"[PRINTER] {printer.name} is offline: {message}")
            self._error_tracker.add(self._status_key(printer))

        status = PrintStatus(
            printer=printer.name,
            state="offline",
            progress_percent=0,
            time_remaining=None,
            time_elapsed=None,
            filename=None,
            temperatures={},
            details=message,
        )
        self._last_status[self._status_key(printer)] = status
        return status
    
    def _detect_orca_profiles_dir(self) -> Optional[str]:
        """Detect OrcaSlicer profiles directory."""
        system = platform.system()
        
        if system == "Darwin":  # macOS
            base = os.path.expanduser("~/Library/Application Support/OrcaSlicer")
        elif system == "Windows":
            base = os.path.join(os.environ.get("APPDATA", ""), "OrcaSlicer")
        else:  # Linux
            base = os.path.expanduser("~/.config/OrcaSlicer")
        
        if os.path.isdir(base):
            print(f"[PRINTER] Found OrcaSlicer profiles at: {base}")
            return base
        
        return None
    
    def get_available_profiles(self) -> Dict[str, List[str]]:
        """
        Get all available OrcaSlicer profiles from the system folder.
        Returns dict with 'machines', 'processes', 'filaments' lists.
        """
        profiles = {"machines": [], "processes": [], "filaments": []}
        
        if not self._orca_profiles_dir:
            return profiles
        
        system_dir = os.path.join(self._orca_profiles_dir, "system")
        if not os.path.isdir(system_dir):
            return profiles
        
        # Scan all vendor folders (Creality, Custom, etc.)
        for vendor in os.listdir(system_dir):
            vendor_path = os.path.join(system_dir, vendor)
            if not os.path.isdir(vendor_path):
                continue
            
            # Machine profiles
            machine_dir = os.path.join(vendor_path, "machine")
            if os.path.isdir(machine_dir):
                for f in os.listdir(machine_dir):
                    if f.endswith(".json"):
                        profiles["machines"].append(f"system/{vendor}/machine/{f}")
            
            # Process profiles
            process_dir = os.path.join(vendor_path, "process")
            if os.path.isdir(process_dir):
                for f in os.listdir(process_dir):
                    if f.endswith(".json"):
                        profiles["processes"].append(f"system/{vendor}/process/{f}")
            
            # Filament profiles
            filament_dir = os.path.join(vendor_path, "filament")
            if os.path.isdir(filament_dir):
                for f in os.listdir(filament_dir):
                    if f.endswith(".json"):
                        profiles["filaments"].append(f"system/{vendor}/filament/{f}")
        
        return profiles
    
    def _find_matching_profile(self, printer_name: str, profile_type: str) -> Optional[str]:
        """
        Find a matching profile for a printer by name.
        profile_type: 'machine', 'process', or 'filament'
        """
        if not self._orca_profiles_dir:
            return None
        
        # Normalize printer name for matching
        # e.g., "Creality K1" -> search for "k1"
        search_terms = printer_name.lower().split()
        
        # Common brand keywords to identify vendor folder
        vendor_map = {
            "creality": "Creality",
            "ender": "Creality",
            "cr-": "Creality",
            "k1": "Creality",
        }
        
        # Try to identify vendor
        vendor = None
        for term in search_terms:
            for key, val in vendor_map.items():
                if key in term:
                    vendor = val
                    break
            if vendor:
                break
        
        if not vendor:
            vendor = "Creality"  # Default fallback
        
        system_dir = os.path.join(self._orca_profiles_dir, "system", vendor)
        if not os.path.isdir(system_dir):
            print(f"[PRINTER] Vendor folder not found: {vendor}")
            return None
        
        target_dir = os.path.join(system_dir, profile_type)
        if not os.path.isdir(target_dir):
            return None
        
        # Score-based matching
        best_match = None
        best_score = 0
        
        for filename in os.listdir(target_dir):
            if not filename.endswith(".json"):
                continue
            
            name_lower = filename.lower()
            score = 0
            
            # Score based on matching search terms
            for term in search_terms:
                if term in name_lower:
                    score += 10
                    # Bonus for exact model match at word boundary
                    # e.g., "k1 " or "k1." matches but "k1c" should score lower
                    if profile_type == "machine":
                        # Check if there's a character after the term that extends it (like C in K1C)
                        idx = name_lower.find(term)
                        if idx >= 0:
                            after_idx = idx + len(term)
                            if after_idx < len(name_lower):
                                next_char = name_lower[after_idx]
                                if next_char.isalpha():
                                    # This is a variant like K1C - penalize it
                                    score -= 8
                                elif next_char in ' .(-':
                                    # Direct match followed by delimiter - bonus
                                    score += 5
            
            # Bonus for "0.4 nozzle" (most common)
            if "0.4" in name_lower:
                score += 2
            
            # Bonus for "standard" or "optimal" process profiles
            if profile_type == "process":
                if "standard" in name_lower:
                    score += 5
                elif "optimal" in name_lower:
                    score += 3
            
            # Bonus for generic PLA filament (non-silk preferred for general use)
            if profile_type == "filament":
                if "pla" in name_lower and "generic" in name_lower:
                    score += 5
                    # Penalize specialty variants
                    if "-cf" in name_lower or "-gf" in name_lower:
                        score -= 5  # Carbon fiber / glass fiber variants
                    if "silk" in name_lower or "matte" in name_lower:
                        score -= 2  # Specialty finishes
                    if "high speed" in name_lower:
                        score -= 1  # Less common
                    # Plain PLA gets a bonus
                    if "@k1" in name_lower and "-" not in name_lower.split("pla")[-1].split("@")[0]:
                        score += 3  # Plain PLA for K1
            
            if score > best_score:
                best_score = score
                best_match = os.path.join(target_dir, filename)
        
        if best_match:
            print(f"[PRINTER] Matched {profile_type} profile: {os.path.basename(best_match)} (score: {best_score})")
        
        return best_match
    
    def get_profiles_for_printer(self, printer_name: str) -> Dict[str, Optional[str]]:
        """
        Auto-detect suitable profiles for a given printer name.
        Returns dict with 'machine', 'process', 'filament' paths.
        """
        return {
            "machine": self._find_matching_profile(printer_name, "machine"),
            "process": self._find_matching_profile(printer_name, "process"),
            "filament": self._find_matching_profile(printer_name, "filament"),
        }
    
    def _detect_slicer_path(self) -> Optional[str]:
        """Detect OrcaSlicer or PrusaSlicer installation path."""
        system = platform.system()
        
        paths = []
        if system == "Darwin":  # macOS
            paths = [
                "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
                "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
                "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"
            ]
        elif system == "Windows":
            paths = [
                r"C:\Program Files\OrcaSlicer\orca-slicer-console.exe",
                r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
                r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
                r"C:\Program Files (x86)\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
                # User/Portable Installs
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "OrcaSlicer", "orca-slicer-console.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "OrcaSlicer", "orca-slicer.exe"),
                os.path.join(os.environ.get("USERPROFILE", ""), "Downloads", "OrcaSlicer", "orca-slicer-console.exe"),
                os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "OrcaSlicer", "orca-slicer-console.exe"),
                os.path.join("C:\\", "OrcaSlicer", "orca-slicer-console.exe")
            ]
        else:  # Linux
            paths = [
                "/usr/bin/orca-slicer",
                os.path.expanduser("~/.local/bin/orca-slicer"),
                "/usr/bin/prusa-slicer",
                "/usr/local/bin/prusa-slicer",
                os.path.expanduser("~/.local/bin/prusa-slicer")
            ]
        
        for path in paths:
            if os.path.exists(path):
                print(f"[PRINTER] Found Slicer at: {path}")
                return path
        
        # Try to find via which/where
        for binary in ["orca-slicer", "prusa-slicer", "prusa-slicer-console"]:
             try:
                result = subprocess.run(
                    ["which", binary] if system != "Windows" else ["where", binary],
                    capture_output=True, text=True
                )
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip().split('\n')[0]
                    print(f"[PRINTER] Found Slicer via PATH: {path}")
                    return path
             except Exception:
                pass
        
        print("[PRINTER] No slicer found. Discovery and status monitoring remain available, but printing is disabled.")
        return None

    async def discover_printers(self, timeout: float = 5.0) -> List[Dict]:
        from devices.printer_discovery import discover_printers
        found = await discover_printers(timeout)
        for printer in found:
            # Discovery must not replace a saved exact endpoint, credentials or protocol.
            if not any(item.host == printer.host for item in self.printers.values()):
                self.printers[printer.host] = printer
                self._set_next_poll(printer.host, 0.0)
        return self.get_printer_list()

    async def _probe_printer_type(self, host, port):
        return PrinterType.UNKNOWN  # No implicit protocol probing.

    async def _probe_camera(self, host, port):
        return None  # Camera access requires a separate explicit workflow.
    
    def add_printer_manually(self, name: str, host: str, port: int = 80, 
                             printer_type: str = "octoprint", api_key: Optional[str] = None,
                             camera_url: Optional[str] = None) -> Printer:
        """Manually add a printer (useful when mDNS discovery fails)."""
        ptype = PrinterType(printer_type) if printer_type in [e.value for e in PrinterType] else PrinterType.UNKNOWN
        existing = self._resolve_printer(f"{host}:{port}")
        if existing and api_key is None:
            api_key = existing.api_key
        printer = Printer(name=name, host=host, port=port, printer_type=ptype, api_key=api_key, camera_url=camera_url)
        previous = self.printers.get(host)
        if previous and previous.port != port:
            self.printers.pop(host)
            self.printers[f"{host}:{previous.port}"] = previous
        key = f"{host}:{port}" if any(item.host == host and item.port != port for item in self.printers.values()) else host
        self.printers[key] = printer
        self._set_next_poll(f"{host}:{port}", 0.0)
        print(f"[PRINTER] Manually added: {name} at {host}:{port}")
        return printer
    
    def _resolve_printer(self, target):
        if target in self.printers:
            return self.printers[target]
        if ":" in target:
            matches = [item for item in self.printers.values() if f"{item.host}:{item.port}" == target]
        else:
            matches = [item for item in self.printers.values() if item.host == target or item.name.lower() == target.lower()]
        return matches[0] if len(matches) == 1 else None

    def _status_key(self, printer):
        return f"{printer.host}:{printer.port}"

    def _resolve_file_path(self, path: str, root_path: Optional[str] = None) -> Optional[str]:
        """Resolve file path by checking common locations."""
        # 1. Check if absolute path exists
        if os.path.isabs(path) and os.path.exists(path):
            return path
            
        common_paths = []
        
        # 2. Check relative to provided root path (Project Directory)
        if root_path:
            common_paths.append(os.path.join(root_path, path))
            # Also check cad subfolder in root if not already in path
            if not path.startswith("cad/"):
                    common_paths.append(os.path.join(root_path, "cad", path))

        # 3. Check relative to backend/current dir
        common_paths.append(path)
        basename = os.path.basename(path)
        
        # 4. Check other heuristics
        common_paths.extend([
            os.path.join("..", basename),   # parent root
            os.path.join("cad", basename),  # cad subdir of backend? 
            os.path.join("..", "cad", basename), # cad subdir of root
            "output.stl",
            "../output.stl"
        ])
        
        for p in common_paths:
            if os.path.exists(p):
                print(f"[PRINTER] Resolved {path} -> {p}")
                return p
        
        return None

    async def slice_stl(self, stl_path: str, output_path: Optional[str] = None,
                        profile_path: Optional[str] = None, 
                        progress_callback: Optional[Any] = None,
                        root_path: Optional[str] = None,
                        printer_name: Optional[str] = None) -> Optional[str]:
        """
        Slice an STL file to G-code using OrcaSlicer/PrusaSlicer CLI.
        
        Args:
            stl_path: Path to input STL file
            output_path: Optional output G-code path (default: same dir as STL)
            profile_path: Optional path to .ini profile file (legacy)
            root_path: Optional root directory to resolve relative paths
            printer_name: Optional printer name for auto-detecting profiles
        
        Returns:
            Path to generated G-code file, or None on failure
        """
        if not self.slicer_path:
            print("[PRINTER] Print request blocked: slicer not found.")
            if progress_callback:
                await progress_callback(0, "Printing unavailable: install OrcaSlicer or PrusaSlicer first.")
            return None
        
        # Robust path resolution
        resolved_path = self._resolve_file_path(stl_path, root_path)
        if not resolved_path:
            print(f"[PRINTER] Error: STL file not found: {stl_path} (root: {root_path})")
            return None
        stl_path = resolved_path
        
        # Default output path - save to project's gcode folder if root_path is provided
        if not output_path:
            if root_path:
                gcode_dir = os.path.join(root_path, "gcode")
                os.makedirs(gcode_dir, exist_ok=True)
                basename = os.path.splitext(os.path.basename(stl_path))[0]
                output_path = os.path.join(gcode_dir, f"{basename}.gcode")
                print(f"[PRINTER] G-code output: {output_path}")
            else:
                output_path = stl_path.rsplit('.', 1)[0] + ".gcode"
        
        # Build command
        is_orca = "OrcaSlicer" in self.slicer_path
        
        if is_orca:
            # OrcaSlicer CLI: orca-slicer [OPTIONS] [file.stl]
            output_dir = os.path.dirname(output_path)
            
            # FIX: Handle empty output_dir (when output_path has no directory prefix)
            if not output_dir:
                output_dir = os.path.dirname(stl_path) or "."
            
            cmd = [
                self.slicer_path,
                "--slice", "0",
                "--outputdir", output_dir,
            ]
            
            # Auto-detect profiles if printer_name is provided
            profiles = None
            if printer_name:
                profiles = self.get_profiles_for_printer(printer_name)
            
            # Build settings string: "machine.json;process.json"
            settings_files = []
            if profiles:
                if profiles.get("machine"):
                    settings_files.append(profiles["machine"])
                if profiles.get("process"):
                    settings_files.append(profiles["process"])
            
            # Add --load-settings if we have profiles
            if settings_files:
                cmd.extend(["--load-settings", ";".join(settings_files)])
                print(f"[PRINTER] Using settings: {[os.path.basename(f) for f in settings_files]}")
            
            # Add --load-filaments if we have filament profile
            if profiles and profiles.get("filament"):
                cmd.extend(["--load-filaments", profiles["filament"]])
                print(f"[PRINTER] Using filament: {os.path.basename(profiles['filament'])}")
            
            # Add STL file at the end
            cmd.append(stl_path)
            
        else:
            # PrusaSlicer CLI
            cmd = [
                self.slicer_path,
                "--export-gcode",
                "--output", output_path,
                stl_path
            ]
        
        # Add legacy profile if specified (for backward compatibility)
        if profile_path and os.path.exists(profile_path):
            if is_orca:
                # Append to existing settings
                cmd_settings_idx = None
                for i, arg in enumerate(cmd):
                    if arg == "--load-settings":
                        cmd_settings_idx = i + 1
                        break
                if cmd_settings_idx and cmd_settings_idx < len(cmd):
                    cmd[cmd_settings_idx] += ";" + profile_path
                else:
                    cmd.insert(-1, "--load-settings")
                    cmd.insert(-1, profile_path)
            else:
                cmd.insert(1, "--load")
                cmd.insert(2, profile_path)
        
        print(f"[PRINTER] Slicing: {stl_path}")
        print(f"[PRINTER] Command: {' '.join(cmd)}")
        
        try:
            # Notify slicing start
            if progress_callback:
                await progress_callback(5, "Starting slicer...")
            
            # Use asyncio.to_thread for Windows compatibility (asyncio.create_subprocess_exec
            # throws NotImplementedError on Windows with certain event loop policies)
            import subprocess
            
            if progress_callback:
                await progress_callback(10, "Running slicer...")
            
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True
                )
                
                # Log slicer output for debugging
                if result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            print(f"[SLICER OUTPUT] {line}")
                
                if progress_callback:
                    await progress_callback(90, "Finalizing...")
                
            except Exception as e:
                print(f"[PRINTER] Subprocess run failed: {e}")
                return None
            
            if result.returncode == 0:
                # Handle OrcaSlicer output naming
                # OrcaSlicer outputs as "plate_1.gcode", "plate_2.gcode" etc.
                if is_orca:
                    output_dir = os.path.dirname(output_path) or "."
                    
                    # Look for plate_*.gcode files (OrcaSlicer naming convention)
                    import glob
                    gcode_files = glob.glob(os.path.join(output_dir, "plate_*.gcode"))
                    
                    if not gcode_files:
                        # Fallback: look for {basename}.gcode
                        base_name = os.path.splitext(os.path.basename(stl_path))[0]
                        expected_gcode = os.path.join(output_dir, f"{base_name}.gcode")
                        if os.path.exists(expected_gcode):
                            gcode_files = [expected_gcode]
                    
                    if gcode_files:
                        # Use the first (or only) plate file
                        actual_gcode = gcode_files[0]
                        if actual_gcode != output_path:
                            import shutil
                            shutil.move(actual_gcode, output_path)
                            print(f"[PRINTER] Renamed {os.path.basename(actual_gcode)} -> {os.path.basename(output_path)}")
                    elif not os.path.exists(output_path):
                        print(f"[PRINTER] Warning: Expected G-code not found in {output_dir}")

                print(f"[PRINTER] Slicing complete: {output_path}")
                if progress_callback:
                    await progress_callback(100, "Slicing Complete")
                return output_path
            else:
                print(f"[PRINTER] Slicing failed: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            print("[PRINTER] Slicing timeout (5 min exceeded)")
            return None
        except Exception as e:
            print(f"[PRINTER] Slicing error: {e}")
            return None
    
    async def upload_gcode(self, target, gcode_path, start_print=False):
        printer = self._resolve_printer(target)
        if not printer or start_print:
            return False  # Upload and physical start remain independently approved.
        return await self.protocol.upload(printer, gcode_path)
    
    async def _upload_octoprint(self, printer, gcode_path, start_print=False):
        if start_print or printer.printer_type != PrinterType.OCTOPRINT:
            return False
        return await self.protocol.upload(printer, gcode_path)

    async def _upload_moonraker(self, printer, gcode_path, start_print=False):
        if start_print or printer.printer_type != PrinterType.MOONRAKER:
            return False
        return await self.protocol.upload(printer, gcode_path)

    async def start_print(self, target, filename):
        printer = self._resolve_printer(target)
        return await self.protocol.start(printer, filename) if printer else False

    async def get_print_status(self, target):
        printer = self._resolve_printer(target)
        if not printer or printer.printer_type not in (PrinterType.MOONRAKER, PrinterType.OCTOPRINT):
            return None
        try:
            status = await self.protocol.status(printer)
            return self._record_status_success(printer, status)
        except Exception:
            return self._record_status_failure(printer, "Status unavailable. Check endpoint, protocol and authorization.")

    async def _status_octoprint(self, printer):
        return await self.get_print_status(printer.host)
    
    async def _status_moonraker(self, printer):
        return await self.get_print_status(printer.host)

    def _format_time(self, seconds: Optional[float]) -> Optional[str]:
        if seconds is None:
            return None
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


    async def print_stl(self, stl_path: str, printer_name: str, 
                        profile_path: Optional[str] = None, 
                        root_path: Optional[str] = None) -> Dict[str, str]:
        """
        Orchestrate the full printing workflow: Slice -> Upload -> Print.
        """
        print(f"[PRINTER] Starting print job for {stl_path} on {printer_name}")
        
        # 1. Resolve Printer
        printer = self._resolve_printer(printer_name)
        if not printer:
            return {"status": "error", "message": f"Printer '{printer_name}' not found."}

        if not self.slicer_path:
            return {
                "status": "error",
                "message": "Printing is unavailable until OrcaSlicer or PrusaSlicer is installed.",
            }

        # 2. Slice STL
        # Use printer name to auto-detect profiles if not provided
        gcode_path = await self.slice_stl(
            stl_path, 
            profile_path=profile_path,
            root_path=root_path,
            printer_name=printer.name 
        )
        
        if not gcode_path:
            return {"status": "error", "message": "Slicing failed check logs."}

        # 3. Upload & Start Print
        success = await self.upload_gcode(printer_name, gcode_path, start_print=True)
        
        if success:
            return {"status": "success", "message": f"Printing {os.path.basename(stl_path)} on {printer.name}"}
        else:
            return {"status": "error", "message": "Failed to upload/start print job."}


# Standalone test
if __name__ == "__main__":
    async def main():
        agent = PrinterAgent()
        
        print("\n=== Testing Printer Discovery ===")
        printers = await agent.discover_printers(timeout=3)
        print(f"Found: {printers}")
        
        if printers:
            printer = printers[0]
            print(f"\n=== Testing Status for {printer['name']} ===")
            status = await agent.get_print_status(printer['host'])
            if status:
                print(f"Status: {status.to_dict()}")
    
    asyncio.run(main())
