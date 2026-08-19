import asyncio
from colorama import init, Fore, Style
import sys
import os

# Add parent directory to path so pipelineguard can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pipelineguard import PipelineGuard, Variant
from tests.fakes import make_factory

init(autoreset=True)

async def main():
    variants = [
        Variant("openai-gpt", "pipelines/openai.pipe", 1.0, 1.0),
        Variant("anthropic-claude", "pipelines/anthropic.pipe", 1.1, 1.05),
        Variant("local-llama", "pipelines/local.pipe", 0.1, 0.8),
    ]

    # FakeClient logic: request 1 succeeds, request 2 fails (triggers failover), request 3 succeeds
    client_factory = make_factory([False, True, False, False])
    guard = PipelineGuard(client_factory=client_factory, variants=variants)

    @guard.on_failover
    def alert(variant, err):
        print(Fore.RED + Style.BRIGHT + f"[!] FAILOVER TRIGGERED: '{variant}' failed with error: {err}")

    @guard.on_cooldown_start
    def cooldown(variant):
        print(Fore.YELLOW + f"[*] '{variant}' has entered a 30s cooldown.")

    print(Fore.CYAN + "=== PipelineGuard Failover Demo ===\n")

    for i in range(1, 4):
        print(Fore.WHITE + Style.BRIGHT + f"\n--- Request {i} ---")
        try:
            report = await guard.run("Summarize this document...")
            if report.ok:
                print(Fore.GREEN + f"[+] Success using variant: {report.variant_used}")
                for a in report.attempts:
                    if not a.ok:
                        print(Fore.RED + f"    - Failed attempt on: {a.variant}")
        except Exception as e:
            print(Fore.RED + f"[-] Entire run failed: {e}")
            
    print(Fore.CYAN + "\n=== Final Scoreboard ===")
    for name, stats in guard.health().items():
        print(Fore.WHITE + f"  {name}: {stats['success_rate']*100:.0f}% success, score: {stats['score']:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
