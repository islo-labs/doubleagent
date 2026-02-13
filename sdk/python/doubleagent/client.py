"""
DoubleAgent client for managing fake services programmatically.
"""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml


@dataclass
class Service:
    """A running DoubleAgent service."""
    
    name: str
    port: int
    url: str
    process: subprocess.Popen
    env: dict[str, str] = field(default_factory=dict)
    
    async def reset(self) -> None:
        """Reset service state."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.url}/_doubleagent/reset")
            resp.raise_for_status()
    
    async def seed(self, data: dict[str, Any]) -> dict[str, Any]:
        """Seed service with data."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.url}/_doubleagent/seed", json=data)
            resp.raise_for_status()
            return resp.json()
    
    async def health(self) -> dict[str, str]:
        """Check service health."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.url}/_doubleagent/health")
            resp.raise_for_status()
            return resp.json()
    
    async def info(self) -> dict[str, Any]:
        """Get service info."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.url}/_doubleagent/info")
            resp.raise_for_status()
            return resp.json()
    
    def stop(self) -> None:
        """Stop the service."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


class DoubleAgent:
    """
    Programmatic interface for running DoubleAgent services.
    
    Usage:
        async with DoubleAgent() as da:
            github = await da.start("github")
            # github.url -> http://localhost:8080
            # Use official SDK pointed at github.url
            await github.reset()
    
    Or without context manager:
        da = DoubleAgent()
        github = await da.start("github")
        # ... use service ...
        da.stop_all()
    """
    
    def __init__(self, services_dir: Optional[Path] = None):
        self.services_dir = services_dir or self._find_services_dir()
        self._services: dict[str, Service] = {}
        self._next_port = 8080
    
    async def __aenter__(self) -> "DoubleAgent":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop_all()
    
    def __enter__(self) -> "DoubleAgent":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop_all()
    
    async def start(
        self,
        service_name: str,
        port: Optional[int] = None,
        timeout: float = 30.0,
    ) -> Service:
        """
        Start a service and wait for it to be healthy.
        
        Args:
            service_name: Name of the service to start
            port: Port to run on (default: auto-assign)
            timeout: Seconds to wait for health check
            
        Returns:
            Service object with url, reset(), seed() methods
        """
        if service_name in self._services:
            return self._services[service_name]
        
        # Load service definition
        service_path = self.services_dir / service_name
        service_yaml = service_path / "service.yaml"
        
        if not service_yaml.exists():
            raise ValueError(f"Service '{service_name}' not found at {service_path}")
        
        with open(service_yaml) as f:
            config = yaml.safe_load(f)
        
        # Determine port
        if port is None:
            port = self._next_port
            self._next_port += 1
        
        # Build command
        server_config = config.get("server", {})
        command = server_config.get("command", ["python", "main.py"])
        
        # Start process
        env = os.environ.copy()
        env["PORT"] = str(port)
        
        # Add configured env vars
        for key, value in server_config.get("env", {}).items():
            env[key] = value.replace("${port}", str(port))
        
        process = subprocess.Popen(
            command,
            cwd=service_path / "server",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        url = f"http://localhost:{port}"
        
        # Build service env for consumers
        service_env = {}
        for key, value in config.get("env", {}).items():
            service_env[key] = value.replace("${port}", str(port))
        
        service = Service(
            name=service_name,
            port=port,
            url=url,
            process=process,
            env=service_env,
        )
        
        # Wait for health
        try:
            await self._wait_for_health(service, timeout)
        except Exception:
            service.stop()
            raise
        
        self._services[service_name] = service
        return service
    
    def start_sync(self, service_name: str, **kwargs) -> Service:
        """Synchronous version of start()."""
        return asyncio.get_event_loop().run_until_complete(
            self.start(service_name, **kwargs)
        )
    
    async def stop(self, service_name: str) -> None:
        """Stop a specific service."""
        if service_name in self._services:
            self._services[service_name].stop()
            del self._services[service_name]
    
    def stop_all(self) -> None:
        """Stop all running services."""
        for service in self._services.values():
            service.stop()
        self._services.clear()
    
    async def _wait_for_health(self, service: Service, timeout: float) -> None:
        """Wait for service to become healthy."""
        url = f"{service.url}/_doubleagent/health"
        start = time.time()
        
        async with httpx.AsyncClient() as client:
            while time.time() - start < timeout:
                try:
                    resp = await client.get(url, timeout=2.0)
                    if resp.status_code == 200:
                        return
                except (httpx.RequestError, httpx.TimeoutException):
                    pass
                
                # Check if process died
                if service.process.poll() is not None:
                    raise RuntimeError(f"Service {service.name} process died")
                
                await asyncio.sleep(0.5)
        
        raise TimeoutError(f"Service {service.name} did not become healthy within {timeout}s")
    
    def _find_services_dir(self) -> Path:
        """Find the services directory."""
        # Check current directory and parents
        cwd = Path.cwd()
        for path in [cwd, *cwd.parents]:
            services = path / "services"
            if services.is_dir():
                return services
        
        # Fall back to relative path
        return Path("services")
