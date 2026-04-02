"""CLI entrypoint for the My Plants deterministic backend."""

from __future__ import annotations

from my_plants.orchestrator import build_default_orchestrator


def main() -> None:
    """Task: Run an interactive CLI loop for the My Plants backend.
    Input: User input from standard input during the CLI session.
    Output: Printed assistant responses for each entered message.
    Failures: Runtime file errors can interrupt the loop and surface exceptions.
    """

    orchestrator = build_default_orchestrator()
    user_id = input("Enter user id [default_user]: ").strip() or "default_user"
    print("My Plants is ready. Type 'exit' to quit.")

    while True:
        message = input("> ").strip()
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        response = orchestrator.handle(user_id=user_id, message=message)
        print(response)


if __name__ == "__main__":
    main()

