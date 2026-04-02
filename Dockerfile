ARG BUILD_FROM
FROM $BUILD_FROM

LABEL \
    io.hass.name="Paperless-ngx MCP Server" \
    io.hass.description="MCP Server für Paperless-ngx mit OAuth 2.0" \
    io.hass.type="addon" \
    io.hass.version="1.1.4"

# Install Node.js
RUN apk add --no-cache nodejs npm

# Install baruchiro paperless-mcp globally
RUN npm install -g @baruchiro/paperless-mcp@latest

# Copy OAuth proxy
COPY src/oauth-proxy.js /app/src/oauth-proxy.js

# Copy startup script
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
