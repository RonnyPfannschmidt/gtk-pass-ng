#!/usr/bin/env python3
"""Example demonstrating the BackgroundService.

This example shows how to use the BackgroundService to run tasks
in background threads without blocking the main thread.
"""

import time
from gtkpass.services.background import BackgroundService


def long_running_task(task_id: int, duration: float) -> str:
    """Simulate a long-running task."""
    print(f"Task {task_id}: Starting (will take {duration}s)...")
    time.sleep(duration)
    result = f"Task {task_id}: Completed after {duration}s"
    print(result)
    return result


def main():
    """Run the example."""
    print("BackgroundService Example")
    print("=" * 50)
    print()

    # Create and initialize the service
    with BackgroundService(max_workers=3) as service:
        print("Service initialized with 3 workers\n")

        # Submit multiple tasks
        futures = []
        for i in range(5):
            future = service.submit(long_running_task, i + 1, (i + 1) * 0.5)
            futures.append(future)

        print(f"Submitted {len(futures)} tasks")
        print("Tasks are running in background threads...\n")

        # Wait for all tasks to complete
        print("Waiting for all tasks to complete...")
        results = []
        for future in futures:
            result = future.result()  # This blocks until the task completes
            results.append(result)

        print("\nAll tasks completed!")
        print("\nResults:")
        for result in results:
            print(f"  - {result}")

    print("\nService cleaned up automatically (context manager)")


if __name__ == "__main__":
    main()
