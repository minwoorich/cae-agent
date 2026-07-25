"""``python -m cae_agent`` 명령으로 CAE Agent를 실행하는 진입점."""

from cae_agent.cli import main


# 패키지를 모듈로 직접 실행한 경우에도 설치된 ``cae-agent`` 명령과 완전히
# 동일한 CLI 함수를 사용한다. 실행 경로를 하나로 통일하면 두 실행 방식의
# 동작이 달라지는 문제를 방지할 수 있다.
if __name__ == "__main__":
    raise SystemExit(main())
