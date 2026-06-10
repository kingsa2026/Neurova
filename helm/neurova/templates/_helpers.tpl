{{/*
Expand the name of the chart.
*/}}
{{- define "neurova.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "neurova.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "neurova.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "neurova.labels" -}}
helm.sh/chart: {{ include "neurova.chart" . }}
{{ include "neurova.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "neurova.selectorLabels" -}}
app.kubernetes.io/name: {{ include "neurova.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend selector labels
*/}}
{{- define "neurova.backend.selectorLabels" -}}
{{ include "neurova.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "neurova.frontend.selectorLabels" -}}
{{ include "neurova.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "neurova.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "neurova.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the proper image name
*/}}
{{- define "neurova.backend.image" -}}
{{- $registryName := .Values.global.imageRegistry -}}
{{- $repositoryName := .Values.backend.image.repository -}}
{{- $separator := ":" -}}
{{- $tagName := .Values.backend.image.tag | default .Chart.AppVersion -}}
{{- if $registryName }}
{{- printf "%s/%s%s%s" $registryName $repositoryName $separator $tagName -}}
{{- else }}
{{- printf "%s%s%s" $repositoryName $separator $tagName -}}
{{- end }}
{{- end }}

{{- define "neurova.frontend.image" -}}
{{- $registryName := .Values.global.imageRegistry -}}
{{- $repositoryName := .Values.frontend.image.repository -}}
{{- $separator := ":" -}}
{{- $tagName := .Values.frontend.image.tag | default .Chart.AppVersion -}}
{{- if $registryName }}
{{- printf "%s/%s%s%s" $registryName $repositoryName $separator $tagName -}}
{{- else }}
{{- printf "%s%s%s" $repositoryName $separator $tagName -}}
{{- end }}
{{- end }}