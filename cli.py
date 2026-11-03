"""
Interactive CLI for the Empório da Música Customer Service AI Agent.

Usage:
    python cli.py
    python cli.py --message "Quais opções de violões disponíveis custando até R$1000?"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from src.agent import EmporioAgent


def print_banner(agent: EmporioAgent) -> None:
    print("=" * 76)
    print(" 🎸 EMPÓRIO DA MÚSICA — Assistente Virtual de Atendimento (Campo Grande/MS)")
    print(f" 🤖 Motor Ativo: {agent.provider} ({agent.model})")
    print(" 💡 Comandos: '/limpar' (nova sessão) | '/sair' (encerrar)")
    print("=" * 76)


def main() -> None:
    parser = argparse.ArgumentParser(description="Empório da Música — AI Customer Service Agent CLI")
    parser.add_argument("--message", "-m", type=str, help="Envia uma única mensagem e exibe a resposta com as tool calls.")
    parser.add_argument("--session", "-s", type=str, default="cli_session", help="ID da sessão para histórico.")
    parser.add_argument("--show-tools", action="store_true", default=True, help="Exibe as ferramentas acionadas.")
    args = parser.parse_args()

    # Ensure UTF-8 output on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    agent = EmporioAgent()

    if args.message:
        res = agent.chat(args.message, session_id=args.session)
        if args.show_tools and res["tool_calls"]:
            print("\n🔧 [Ferramentas Acionadas pelo Agente]:")
            for tc in res["tool_calls"]:
                print(f"  -> {tc['tool']}({json.dumps(tc['args'], ensure_ascii=False)})")
        print(f"\n🎸 Tom (Empório da Música):\n{res['reply']}\n")
        return

    print_banner(agent)
    while True:
        try:
            user_input = input("\n👤 Cliente: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo! 🎶 Empório da Música — Sua música começa aqui.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/sair", "/exit", "sair", "exit", "quit"):
            print("\nAté logo! 🎶 Empório da Música — Sua música começa aqui.")
            break
        if user_input.lower() in ("/limpar", "/reset", "reset"):
            agent.memory.clear(args.session)
            print("🧹 Histórico da sessão reiniciado!")
            continue

        res = agent.chat(user_input, session_id=args.session)
        if args.show_tools and res["tool_calls"]:
            print("\n  🔧 [Tools executadas]:")
            for tc in res["tool_calls"]:
                print(f"     • {tc['tool']}({json.dumps(tc['args'], ensure_ascii=False)})")
        print(f"\n🎸 Tom (Empório da Música):\n{res['reply']}")


if __name__ == "__main__":
    main()
