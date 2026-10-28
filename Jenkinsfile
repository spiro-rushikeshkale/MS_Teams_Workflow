pipeline {
    agent any

    triggers {
        // Runs roughly every 10 minutes. Jenkins' "H" (hash) symbol picks a
        // consistent offset based on the job name instead of firing exactly
        // on the round minute, to spread load across the shared Jenkins server.
        cron('H/10 * * * *')
    }

    environment {
        TEAMS_WEBHOOK_URL     = credentials('TEAMS_WEBHOOK_URL')
        ENERGY_API_BASE_URL   = credentials('ENERGY_API_BASE_URL')
        ENERGY_API_KEY        = credentials('ENERGY_API_KEY')
        ENERGY_AUTH_KEY       = credentials('ENERGY_AUTH_KEY')
        ENERGY_TEST_DIAL_CODE = credentials('ENERGY_TEST_DIAL_CODE')
        ENERGY_TEST_PASSWORD  = credentials('ENERGY_TEST_PASSWORD')
    }

    stages {
        stage('Install dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }
        stage('Run health check') {
            steps {
                sh 'python3 scripts/api_health_check.py'
            }
        }
    }
}
