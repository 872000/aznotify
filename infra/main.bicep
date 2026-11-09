// aznotify infrastructure: Function App (Consumption) + Storage queues +
// Application Insights. Deploy with the commands in the README.
// No secrets are stored here: the Function App's storage connection string
// is built at deploy time from the storage account key via listKeys().

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Base name for resources (lowercase letters and digits). Keep it short: the storage account name is derived from it and must stay under 24 characters.')
@minLength(3)
@maxLength(16)
param baseName string = 'aznotify'

@description('Environment suffix, e.g. dev, staging, prod.')
param environment string = 'dev'

@description('Storage account redundancy.')
@allowed(['Standard_LRS', 'Standard_GRS'])
param storageSku string = 'Standard_LRS'

@description('Default notification sender. "console" logs instead of sending; switch to a real provider sender only after implementing its stub in senders.py.')
@allowed(['console', 'smtp', 'twilio', 'firebase'])
param defaultSender string = 'console'

var storageAccountName = toLower('${baseName}${environment}sa')
var functionAppName = '${baseName}-${environment}-func'
var planName = '${baseName}-${environment}-plan'
var insightsName = '${baseName}-${environment}-insights'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: storageSku
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource notificationsQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'notifications'
}

resource poisonQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'notifications-poison'
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true // Linux Consumption plan
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.12'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: insights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: insights.properties.ConnectionString
        }
        {
          name: 'NOTIFICATION_QUEUE_NAME'
          value: 'notifications'
        }
        {
          name: 'NOTIFICATION_POISON_QUEUE_NAME'
          value: 'notifications-poison'
        }
        {
          name: 'AZNOTIFY_SENDER'
          value: defaultSender
        }
      ]
    }
  }
}

output functionAppName string = functionApp.name
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output storageAccountName string = storage.name
output appInsightsName string = insights.name
output notificationQueue string = notificationsQueue.name
output poisonQueue string = poisonQueue.name
