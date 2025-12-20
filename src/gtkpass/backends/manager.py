"""Backend manager for GTKPass.

Discovers and manages multiple password storage backends using entry points.
"""

import concurrent.futures
from importlib.metadata import entry_points
from pathlib import Path
from typing import Callable, List, Optional, Type

from . import PasswordBackend, PasswordEntry, PasswordMetadata, BackendError


class BackendManager:
    """Manages multiple password backends.
    
    Discovers backends via entry points, initializes selected backends,
    and provides a unified interface for password operations across
    multiple backends.
    """

    def __init__(self):
        """Initialize backend manager."""
        self._backends: dict[str, PasswordBackend] = {}
        self._backend_classes: dict[str, Type[PasswordBackend]] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    
    def discover_backends(self) -> List[Type[PasswordBackend]]:
        """Discover all available backends via entry points.
        
        Returns:
            List of backend classes
        """
        discovered = []
        
        # Discover entry points
        try:
            eps = entry_points(group="gtkpass.backends")
        except TypeError:
            # Python < 3.10 compatibility
            eps = entry_points().get("gtkpass.backends", [])
        
        for ep in eps:
            try:
                backend_class = ep.load()
                backend_id = backend_class.metadata.id
                
                discovered.append(backend_class)
                self._backend_classes[backend_id] = backend_class
            
            except Exception as e:
                print(f"Warning: Failed to load backend {ep.name}: {e}")
        
        return discovered
    
    def initialize_backend(
        self,
        backend_id: str,
        **kwargs
    ) -> None:
        """Initialize a backend.
        
        Args:
            backend_id: Backend identifier
            **kwargs: Backend-specific initialization parameters
        
        Raises:
            ValueError: If backend not found
            RuntimeError: If initialization fails
        """
        if backend_id not in self._backend_classes:
            raise ValueError(f"Backend '{backend_id}' not found")
        
        backend_class = self._backend_classes[backend_id]
        
        # Use the create() factory method
        backend = backend_class.create(**kwargs)
        if backend is None:
            raise RuntimeError(f"Backend '{backend_id}' initialization failed")
        
        self._backends[backend_id] = backend
    
    def add_backend(self, backend_id: str, backend: PasswordBackend) -> None:
        """Add an already-initialized backend.
        
        Args:
            backend_id: Unique identifier for this backend instance
            backend: Initialized backend instance
        """
        self._backends[backend_id] = backend
    
    def get_backend(self, backend_id: str) -> Optional[PasswordBackend]:
        """Get an initialized backend.
        
        Args:
            backend_id: Backend identifier
        
        Returns:
            Backend instance or None if not initialized
        """
        return self._backends.get(backend_id)
    
    def get_all_backends(self) -> dict[str, PasswordBackend]:
        """Get all initialized backends.
        
        Returns:
            Dictionary of backend_id -> backend instance
        """
        return self._backends.copy()
    
    def list_all_backends(self) -> List[Type[PasswordBackend]]:
        """List all discovered backend classes.
        
        Returns:
            List of backend classes
        """
        return list(self._backend_classes.values())
    
    def list_active_backends(self) -> List[Type[PasswordBackend]]:
        """List initialized backend classes.
        
        Returns:
            List of backend classes for initialized backends
        """
        return [
            self._backend_classes[backend_id]
            for backend_id in self._backends.keys()
            if backend_id in self._backend_classes
        ]
    
    def list_passwords_async(
        self,
        backend_id: str,
        prefix: str = "",
        callback: Optional[Callable[[List[PasswordMetadata]], None]] = None,
    ) -> concurrent.futures.Future:
        """List passwords asynchronously from a backend.
        
        Args:
            backend_id: Backend identifier
            prefix: Optional prefix filter
            callback: Optional callback to invoke with results
        
        Returns:
            Future that will contain list of PasswordMetadata
        
        Raises:
            ValueError: If backend not initialized
        """
        backend = self._backends.get(backend_id)
        if not backend:
            raise ValueError(f"Backend '{backend_id}' not initialized")
        
        def _list():
            result = backend.list_passwords(prefix)
            if callback:
                callback(result)
            return result
        
        return self._executor.submit(_list)
    
    def get_password_async(
        self,
        backend_id: str,
        name: str,
        callback: Optional[Callable[[PasswordEntry], None]] = None,
    ) -> concurrent.futures.Future:
        """Get a password asynchronously from a backend.
        
        Args:
            backend_id: Backend identifier
            name: Password name
            callback: Optional callback to invoke with result
        
        Returns:
            Future that will contain PasswordEntry
        
        Raises:
            ValueError: If backend not initialized
        """
        backend = self._backends.get(backend_id)
        if not backend:
            raise ValueError(f"Backend '{backend_id}' not initialized")
        
        def _get():
            result = backend.get_password(name)
            if callback:
                callback(result)
            return result
        
        return self._executor.submit(_get)
    
    def search_all_backends(self, query: str) -> dict[str, List[PasswordMetadata]]:
        """Search across all active backends.
        
        Args:
            query: Search query
        
        Returns:
            Dictionary of backend_id -> list of matching passwords
        """
        results = {}
        
        for backend_id, backend in self._backends.items():
            try:
                matches = backend.search(query)
                if matches:
                    results[backend_id] = matches
            except Exception as e:
                print(f"Warning: Search failed in backend '{backend_id}': {e}")
        
        return results
    
    def copy_password_between_backends(
        self,
        source_backend_id: str,
        dest_backend_id: str,
        name: str,
        dest_name: Optional[str] = None,
    ) -> None:
        """Copy a password from one backend to another.
        
        Args:
            source_backend_id: Source backend identifier
            dest_backend_id: Destination backend identifier
            name: Password name in source backend
            dest_name: Name for password in destination (default: same as source)
        
        Raises:
            ValueError: If backend not initialized
            FileNotFoundError: If source password doesn't exist
            FileExistsError: If destination password exists
            BackendError: If copy fails
        """
        source = self._backends.get(source_backend_id)
        dest = self._backends.get(dest_backend_id)
        
        if not source:
            raise ValueError(f"Source backend '{source_backend_id}' not initialized")
        if not dest:
            raise ValueError(f"Destination backend '{dest_backend_id}' not initialized")
        
        dest_name = dest_name or name
        
        # Get password from source
        entry = source.get_password(name)
        
        # Add to destination
        if entry.content:
            dest.add_password(dest_name, entry.content)
    
    def shutdown(self):
        """Shutdown backend manager and cleanup resources."""
        self._executor.shutdown(wait=True)
        self._backends.clear()
