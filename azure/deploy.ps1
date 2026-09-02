[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [string]$ResourceGroup = "thermolens-rg",
    [string]$Location = "centralindia",
    [string]$AppName = "thermolens-api",
    [string]$StorageAccountName = "",
    [string]$FirmsApiKey = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required. Install it from https://aka.ms/installazurecliwindows, then run az login."
}

if (-not $StorageAccountName) {
    $StorageAccountName = ("thermolens" + (Get-Random -Minimum 100000 -Maximum 999999)).ToLower()
}

$ContainerName = "datasets"
$BlobName = "factory_roster_2yr.parquet"
$DatasetPath = Join-Path $PSScriptRoot "..\data\factory_roster_2yr.parquet"

if (-not (Test-Path -LiteralPath $DatasetPath)) {
    throw "Factory roster not found at $DatasetPath"
}

az extension add --name containerapp --upgrade --only-show-errors
az provider register --namespace Microsoft.App --wait
az group create --name $ResourceGroup --location $Location --output none
az storage account create --name $StorageAccountName --resource-group $ResourceGroup --location $Location --sku Standard_LRS --kind StorageV2 --allow-blob-public-access false --output none

$StorageKey = az storage account keys list --account-name $StorageAccountName --resource-group $ResourceGroup --query "[0].value" --output tsv
az storage container create --name $ContainerName --account-name $StorageAccountName --account-key $StorageKey --public-access off --output none
az storage blob upload --container-name $ContainerName --name $BlobName --file $DatasetPath --account-name $StorageAccountName --account-key $StorageKey --overwrite true --output none

az containerapp up --name $AppName --resource-group $ResourceGroup --location $Location --source (Resolve-Path (Join-Path $PSScriptRoot "..")) --ingress external --target-port 8000 --cpu 2.0 --memory 4.0Gi --min-replicas 1 --max-replicas 1
az containerapp identity assign --name $AppName --resource-group $ResourceGroup --system-assigned --output none

$PrincipalId = az containerapp identity show --name $AppName --resource-group $ResourceGroup --query principalId --output tsv
$StorageId = az storage account show --name $StorageAccountName --resource-group $ResourceGroup --query id --output tsv
az role assignment create --assignee-object-id $PrincipalId --assignee-principal-type ServicePrincipal --role "Storage Blob Data Reader" --scope $StorageId --output none

az containerapp secret set --name $AppName --resource-group $ResourceGroup --secrets "database-url=$DatabaseUrl" --output none
$EnvironmentVariables = @(
    "DATABASE_URL=secretref:database-url",
    "AZURE_STORAGE_ACCOUNT_URL=https://$StorageAccountName.blob.core.windows.net",
    "AZURE_ROSTER_CONTAINER=$ContainerName",
    "AZURE_ROSTER_BLOB=$BlobName"
)
if ($FirmsApiKey) {
    az containerapp secret set --name $AppName --resource-group $ResourceGroup --secrets "firms-api-key=$FirmsApiKey" --output none
    $EnvironmentVariables += "FIRMS_API_KEY=secretref:firms-api-key"
}

az containerapp update --name $AppName --resource-group $ResourceGroup --cpu 2.0 --memory 4.0Gi --min-replicas 1 --max-replicas 1 --set-env-vars $EnvironmentVariables --output none

$Fqdn = az containerapp show --name $AppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn --output tsv
Write-Host "Deployment complete: https://$Fqdn"
