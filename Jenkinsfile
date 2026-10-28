pipeline {
    agent any

    triggers {
        // Runs roughly every 10 minutes. Jenkins' "H" (hash) symbol picks a
        // consistent offset based on the job name instead of firing exactly
        // on the round minute, to spread load across the shared Jenkins server.
        cron('H/10 * * * *')
    }

    // Temporary: reading secrets from job Build Parameters (set via the job's
    // own Configure page) instead of the Jenkins Credentials store, since that
    // store needs DevOps/admin access this job doesn't have yet. Values live
    // only in Jenkins job config, never in this file/git. Switch back to
    // credentials('X') once Credentials access is granted.
    environment {
        TEAMS_WEBHOOK_URL     = "${params.TEAMS_WEBHOOK_URL}"
        ENERGY_API_BASE_URL   = "${params.ENERGY_API_BASE_URL}"
        ENERGY_API_KEY        = "${params.ENERGY_API_KEY}"
        ENERGY_AUTH_KEY       = "${params.ENERGY_AUTH_KEY}"
        ENERGY_TEST_DIAL_CODE = "${params.ENERGY_TEST_DIAL_CODE}"
        ENERGY_TEST_PASSWORD  = "${params.ENERGY_TEST_PASSWORD}"
    }

    stages {
        stage('Install dependencies') {
            steps {
                // The agent's system Python blocks "pip install" directly
                // (PEP 668 "externally managed environment"), so use an
                // isolated virtual environment instead of forcing it.
                sh '''
                    python3 -m venv .venv
                    .venv/bin/pip install --upgrade pip
                    .venv/bin/pip install -r requirements.txt
                '''
            }
        }
        stage('Run health check') {
            steps {
                sh '.venv/bin/python scripts/api_health_check.py'
            }
        }
    }
}
