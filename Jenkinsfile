// 품질 게이트 파이프라인 (CLAUDE.md "CI (Jenkins)" 절)
// 빌드 노드: Jenkins 내장 노드 (Windows 11, 서비스 계정 LocalSystem).
// Python 경로는 Jenkins 전역 환경 변수 PYTHON312로 바꿀 수 있고, 없으면 아래 기본값을 쓴다.
pipeline {
    agent any

    options {
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    environment {
        PYTHON312 = "${env.PYTHON312 ?: 'C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python312\\python.exe'}"
        PYTHONUTF8 = '1'
        PYTHONIOENCODING = 'utf-8'
        VENV_PY = '.venv\\Scripts\\python.exe'
    }

    stages {
        stage('환경 준비') {
            steps {
                bat '"%PYTHON312%" --version'
                bat '"%PYTHON312%" -m venv --clear .venv'
                bat '%VENV_PY% -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt'
            }
        }
        stage('정적 분석 (Ruff)') {
            steps {
                bat '%VENV_PY% -m ruff check .'
                bat '%VENV_PY% -m ruff format --check .'
            }
        }
        stage('타입 검사 (mypy)') {
            steps {
                bat '%VENV_PY% -m mypy'
            }
        }
        stage('단위 테스트 + 브랜치 커버리지 100%') {
            steps {
                bat '%VENV_PY% -m pytest -p no:cacheprovider --cov --cov-branch --cov-fail-under=100 --cov-report=xml --junitxml=reports\\junit.xml'
            }
        }
        stage('함수 길이·주석률') {
            steps {
                bat '%VENV_PY% -m tools.check_metrics src tools'
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/junit.xml'
            archiveArtifacts allowEmptyArchive: true, artifacts: 'coverage.xml'
        }
    }
}
