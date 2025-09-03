FROM python:3.11-alpine

# Installer nginx
RUN apk add --no-cache nginx

# Créer répertoire de travail
WORKDIR /app

# Copier les fichiers du projet
COPY ./content ./content
COPY ./public ./public
COPY ./build.py ./build.py
COPY ./requirements.txt ./requirements.txt

# Builder le site
RUN python3 -m pip install -r requirements.txt
RUN python3 build.py

# Copier la configuration nginx
COPY nginx.conf /etc/nginx/http.d/tinyblog.conf

# Supprimer la config par défaut d'Alpine
RUN rm -f /etc/nginx/http.d/default.conf

# Créer les répertoires nécessaires et ajuster les permissions
RUN mkdir -p /var/log/nginx /var/lib/nginx/tmp && \
    chown -R nginx:nginx /var/log/nginx /var/lib/nginx /app/build

# Utilisateur non-root
USER nginx

# Exposer le port
EXPOSE 80

# Démarrer nginx
CMD ["nginx", "-g", "daemon off;"]