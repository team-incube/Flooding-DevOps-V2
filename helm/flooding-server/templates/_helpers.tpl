{{/*
Expand the name of the chart.
*/}}
{{- define "flooding-server.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "flooding-server.fullname" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "flooding-server.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{ include "flooding-server.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "flooding-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "flooding-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
