// 품질 게이트 파이프라인 (CLAUDE.md "CI (Jenkins)" 절)
// 가정: Linux 에이전트에 python3.12 가 설치되어 있다. (Jenkins 연동 방식은 확인 필요 항목)
pipeline {
    agent any

    stages {
        stage('환경 준비') {
            steps {
                sh '''
                    python3.12 -m venv .venv
                    .venv/bin/pip install --quiet -r requirements-dev.txt
                '''
            }
        }
        stage('정적 분석 (Ruff)') {
            steps {
                sh '.venv/bin/ruff check .'
                sh '.venv/bin/ruff format --check .'
            }
        }
        stage('단위 테스트 + 브랜치 커버리지 100%') {
            steps {
                sh '''
                    .venv/bin/python -m pytest --cov --cov-branch \
                        --cov-fail-under=100 --cov-report=xml \
                        --junitxml=reports/junit.xml
                '''
            }
        }
        stage('함수 길이·주석률') {
            steps {
                sh '.venv/bin/python -m tools.check_metrics src tools'
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
