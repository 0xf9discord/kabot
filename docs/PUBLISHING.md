# PyPI 배포 (0.4.0)

패키지 이름은 `kabot-python`, import 이름은 `kabot`입니다.
PyPI 소개에는 `PYPI_README.md`를 사용합니다. 저장소 주소와 연락처는 확인된 값이
없어 메타데이터에 임의로 넣지 않았습니다. 작성자 표기는 기존 MIT 라이선스와 같은
`Kabot contributors`입니다.

## 빌드·검증

프로젝트 폴더에서 실행합니다.

```powershell
python -m pip install -e ".[dev,loco]"
python -m pytest -q
python tools/build_release.py
```

이 스크립트는 업로드하지 않습니다. 현재 버전만 `dist/pypi/0.4.0/`에 빌드하고
메타데이터, README 렌더링, 아카이브 경로, 민감 파일 제외 여부를 검사합니다.
이 폴더의 두 배포 파일과 `SHA256SUMS.txt`를 확인하세요.
연구용 실행 파일·메모리 덤프·IDA DB·참고 저장소·로그인 세션은 포함하지 않습니다.
이전 버전이 섞일 수 있는 `dist/*` 전체를 업로드하지 마세요.

## TestPyPI 업로드 (선택)

TestPyPI 계정과 토큰은 정식 PyPI와 별개입니다.

```powershell
python -m twine upload --repository testpypi --username __token__ dist/pypi/0.4.0/kabot_python-0.4.0-py3-none-any.whl dist/pypi/0.4.0/kabot_python-0.4.0.tar.gz
```

토큰은 실행한 터미널의 비밀번호 입력란에 직접 입력하세요.
이 문서, 소스 코드, 명령 인자나 채팅에 토큰을 넣지 않습니다.

## 정식 PyPI 업로드

[PyPI 계정](https://pypi.org/account/register/)에서 계정 설정과 2단계 인증을 완료하고,
[API 토큰](https://pypi.org/manage/account/token/)을 발급받습니다.
첫 프로젝트 생성에는 해당 프로젝트를 생성할 권한이 있는 토큰이 필요합니다.
생성 이후에는 프로젝트 범위 토큰을 사용할 수 있습니다.

다음 명령은 실제로 패키지를 공개합니다.

```powershell
python -m twine upload --username __token__ dist/pypi/0.4.0/kabot_python-0.4.0-py3-none-any.whl dist/pypi/0.4.0/kabot_python-0.4.0.tar.gz
```

업로드 성공 후 새 가상환경에서 설치합니다.

```powershell
python -m pip install "kabot-python[loco]==0.4.0"
kabot --help
kabot open-profile --help
```

공개 위치는 `https://pypi.org/project/kabot-python/0.4.0/`입니다.
같은 버전의 파일은 덮어쓸 수 없으므로 배포 내용을 바꾸면
`pyproject.toml`과 `src/kabot/__init__.py`의 버전을 함께 올린 뒤 재빌드하세요.
이름이 조회되지 않더라도 최종 이름 사용 가능 여부는 PyPI의 업로드 검사가 결정합니다.

공식 안내: [패키징·업로드](https://packaging.python.org/en/latest/tutorials/packaging-projects/),
[PyPI 토큰](https://pypi.org/help/#apitoken).
