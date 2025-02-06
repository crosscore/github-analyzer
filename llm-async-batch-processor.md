# Repository Structure

```
├── alembic
│   ├── versions
│   │   └── create_llm_results.py
│   └── env.py
├── app
│   ├── __init__.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   └── tasks.py
├── config
│   ├── __init__.py
│   └── settings.py
├── web
│   ├── src
│   │   ├── app
│   │   │   ├── globals.css
│   │   │   ├── layout.js
│   │   │   └── pages.js
│   │   └── components
│   │       └── Dashboard.jsx
│   ├── next.config.js
│   ├── package.json
│   ├── postcss.config.js
│   └── tailwind.config.js
├── .env.example
├── Dockerfile
├── Dockerfile.web
├── alembic.ini
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── setup_path.py
```

# File Contents

## alembic/versions/create_llm_results.py

```
# alembic/versions/create_llm_results.py
"""create llm_results table with chain processing
Revision ID: create_llm_results_chain
Revises: 
Create Date: 2025-02-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'create_llm_results_chain'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'llm_results',
        sa.Column('task_id', sa.String, primary_key=True, nullable=False),
        sa.Column('chain_id', sa.String, nullable=False, index=True),
        sa.Column('step_number', sa.Integer, nullable=False),
        sa.Column('prompt', sa.Text, nullable=False),
        sa.Column('response', sa.Text, nullable=True),
        sa.Column('status', sa.String, nullable=False),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('execution_time_ms', sa.Integer, nullable=True),
    )

def downgrade():
    op.drop_table('llm_results')

```

## alembic/env.py

```
# alembic/env.py
import setup_path
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from app.models import Base
from config.settings import settings

# Alembic Config object
config = context.config

# Dynamically set the SQLAlchemy URL using settings
config.set_main_option("sqlalchemy.url", settings.postgres_url)

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# Set target metadata for 'autogenerate'
target_metadata = Base.metadata

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

```

## app/__init__.py

```

```

## app/database.py

```
# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.settings import settings

engine = create_engine(settings.postgres_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

```

## app/main.py

```
# app/main.py
import setup_path
import os
import shortuuid
from fastapi import FastAPI, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from app.tasks import process_chain_task, process_chain_batch_task
from app.database import SessionLocal
from app.models import LLMResult
from config.settings import settings
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="LLM Async Hub (Simplified)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/process_chain")
async def process_chain(request: Request):
    try:
        data = await request.json()
        input_text = data.get("input_text")
    except Exception:
        input_text = None

    if input_text:
        # Process single input provided via API request
        chain_id = shortuuid.uuid()
        task = process_chain_task.apply_async(args=[chain_id, input_text])
        return {"chain_id": chain_id, "task_id": task.id}
    else:
        # Process text files from input folder in batches
        input_folder = settings.input_folder_path
        texts = []
        for root, dirs, files in os.walk(input_folder):
            for file in files:
                if file.endswith(".txt"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        texts.append(f.read())
        if not texts:
            raise HTTPException(status_code=400, detail="No input_text provided and no text files found")

        responses = []
        batch_size = settings.llm_batch_size
        # Group texts into batches
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            batch_id = shortuuid.uuid()
            task = process_chain_batch_task.apply_async(args=[batch_id, batch])
            responses.append({"batch_id": batch_id, "task_id": task.id, "batch_size": len(batch)})
        return responses

@app.get("/llm_results")
def read_llm_results(db: Session = Depends(get_db)):
    try:
        results = db.query(LLMResult).order_by(LLMResult.chain_id, LLMResult.step_number).all()
        chains = {}
        for r in results:
            chains.setdefault(r.chain_id, []).append(serialize_llm_result(r))
        return chains
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def serialize_llm_result(result: LLMResult):
    return {
        "task_id": result.task_id,
        "chain_id": result.chain_id,
        "step_number": result.step_number,
        "prompt": result.prompt,
        "response": result.response,
        "status": result.status,
        "error_message": result.error_message,
        "created_at": result.created_at,
        "completed_at": result.completed_at,
        "execution_time_ms": result.execution_time_ms
    }

```

## app/models.py

```
# app/models.py
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Integer, Text, DateTime
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
Base = declarative_base()

class LLMResult(Base):
    __tablename__ = "llm_results"

    task_id = Column(String, primary_key=True, index=True)  # shortuuid
    chain_id = Column(String, nullable=False, index=True)   # shortuuid
    step_number = Column(Integer, nullable=False)           # 1-3
    prompt = Column(Text, nullable=False)
    response = Column(Text)
    status = Column(String, nullable=False)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(JST))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    execution_time_ms = Column(Integer)

```

## app/tasks.py

```
# app/tasks.py
import setup_path
import logging
import shortuuid
from datetime import datetime
from zoneinfo import ZoneInfo
from celery import Celery
from tenacity import retry, stop_after_attempt, wait_random_exponential
from openai import AzureOpenAI
from config.settings import settings
from app.database import SessionLocal
from app.models import LLMResult

JST = ZoneInfo('Asia/Tokyo')
celery_app = Celery(
    "tasks",
    broker=settings.redis_broker_url,
    backend=settings.celery_backend_url,
    broker_connection_retry_on_startup=True
)

def now_jst():
    # Return a naive datetime representing JST
    return datetime.now(JST).replace(tzinfo=None)

def get_azure_client():
    return AzureOpenAI(
        api_key=settings.azure_api_key,
        api_version=settings.api_version,
        azure_endpoint=settings.azure_endpoint
    )

@retry(stop=stop_after_attempt(10), wait=wait_random_exponential(multiplier=1, max=30))
def call_azure_openai(client: AzureOpenAI, prompt: str, model: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        top_p=settings.llm_top_p,
        frequency_penalty=settings.llm_frequency_penalty,
        presence_penalty=settings.llm_presence_penalty,
    )
    return response.choices[0].message.content

@celery_app.task(name="process_chain_task", bind=True)
def process_chain_task(self, chain_id: str, input_text: str):
    client = get_azure_client()
    session = SessionLocal()
    results = {}
    try:
        for step in [1, 2, 3]:
            start_time = now_jst() # naive JST datetime
            if step == 1:
                prompt = settings.prompt_templates["step1"].format(input_text=input_text)
            elif step == 2:
                prompt = settings.prompt_templates["step2"].format(step1_response=results.get("step1"))
            elif step == 3:
                prompt = settings.prompt_templates["step3"].format(
                    step1_response=results.get("step1"),
                    step2_response=results.get("step2")
                )

            response_text = call_azure_openai(client, prompt, settings.openai_model)
            completed_at = now_jst()
            exec_time = int((completed_at - start_time).total_seconds() * 1000)
            results[f"step{step}"] = response_text

            task_id = shortuuid.uuid()
            llm_result = LLMResult(
                task_id=task_id,
                chain_id=chain_id,
                step_number=step,
                prompt=prompt,
                response=response_text,
                status="success",
                created_at=start_time,
                completed_at=completed_at,
                execution_time_ms=exec_time
            )
            session.add(llm_result)
            session.commit()
        return {"chain_id": chain_id, "results": results}
    except Exception as e:
        error_time = now_jst()
        llm_result = LLMResult(
            task_id=f"{self.request.id}_{step}" if 'step' in locals() else self.request.id,
            chain_id=chain_id,
            step_number=step if 'step' in locals() else None,
            prompt=prompt if 'prompt' in locals() else "",
            status="error",
            error_message=str(e),
            created_at=start_time if 'start_time' in locals() else error_time,
            completed_at=error_time
        )
        session.add(llm_result)
        session.commit()
        raise e
    finally:
        session.close()

@celery_app.task(name="process_chain_batch_task", bind=True)
def process_chain_batch_task(self, batch_id: str, texts: list):
    client = get_azure_client()
    session = SessionLocal()
    results_summary = []
    for input_text in texts:
        chain_id = shortuuid.uuid()
        results = {}
        try:
            for step in [1, 2, 3]:
                start_time = now_jst()
                if step == 1:
                    prompt = settings.prompt_templates["step1"].format(input_text=input_text)
                elif step == 2:
                    prompt = settings.prompt_templates["step2"].format(step1_response=results.get("step1"))
                elif step == 3:
                    prompt = settings.prompt_templates["step3"].format(
                        step1_response=results.get("step1"),
                        step2_response=results.get("step2")
                    )
                response_text = call_azure_openai(client, prompt, settings.openai_model)
                completed_at = now_jst()
                exec_time = int((completed_at - start_time).total_seconds() * 1000)
                results[f"step{step}"] = response_text

                llm_result = LLMResult(
                    task_id=shortuuid.uuid(),
                    chain_id=chain_id,
                    step_number=step,
                    prompt=prompt,
                    response=response_text,
                    status="success",
                    created_at=start_time,
                    completed_at=completed_at,
                    execution_time_ms=exec_time
                )
                session.add(llm_result)
                session.commit()
            results_summary.append({"chain_id": chain_id, "results": results})
        except Exception as e:
            error_time = now_jst()
            llm_result = LLMResult(
                task_id=f"{self.request.id}_{chain_id}_{step}" if 'step' in locals() else self.request.id,
                chain_id=chain_id,
                step_number=step if 'step' in locals() else None,
                prompt=prompt if 'prompt' in locals() else "",
                status="error",
                error_message=str(e),
                created_at=start_time if 'start_time' in locals() else error_time,
                completed_at=error_time
            )
            session.add(llm_result)
            session.commit()
            results_summary.append({"chain_id": chain_id, "error": str(e)})
    session.close()
    return {"batch_id": batch_id, "results_summary": results_summary}

```

## config/__init__.py

```

```

## config/settings.py

```
# config/settings.py
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseSettings):
    # Database
    postgres_url: str = os.getenv("POSTGRES_URL")
    
    # Azure OpenAI settings
    azure_api_key: str = os.getenv("AZURE_API_KEY")
    azure_endpoint: str = os.getenv("AZURE_ENDPOINT")
    api_version: str = os.getenv("API_VERSION")
    openai_model: str = os.getenv("OPENAI_MODEL")

    # Redis and Celery settings
    redis_broker_url: str = os.getenv("REDIS_BROKER_URL")
    celery_backend_url: str = os.getenv("CELERY_BACKEND_URL")
    
    # LLM Parameters
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", 0.2))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", 1024))
    llm_top_p: float = float(os.getenv("LLM_TOP_P", 0.95))
    llm_frequency_penalty: float = float(os.getenv("LLM_FREQUENCY_PENALTY", 0.0))
    llm_presence_penalty: float = float(os.getenv("LLM_PRESENCE_PENALTY", 0.0))
    llm_batch_size: int = int(os.getenv("LLM_BATCH_SIZE", 5))

    # File Paths
    input_folder_path: str = os.getenv("INPUT_FOLDER_PATH", "app/data/input")

    # prompt templates for 3-step chain
    prompt_templates: dict = {
        "step1": """
            質問:
            {input_text}
        """,
        "step2": """
            質問:
            以下に記載した**1回目の回答**に1を加算した時の答えの数字だけを回答して下さい。

            1回目の回答:
            {step1_response}
        """,
        "step3": """
            質問:
            以下に記載した**1回目の回答**と**2回目の回答**の差の絶対値となる答えの数字だけを回答して下さい。

            1回目の回答:
            {step1_response}

            2回目の回答:
            {step2_response}
        """
    }

    class Config:
        env_file = ".env"

settings = Settings()

```

## web/src/app/globals.css

```
@tailwind base;
@tailwind components;
@tailwind utilities;
```

## web/src/app/layout.js

```
import './globals.css'

export const metadata = {
  title: 'LLM Chain Results Dashboard',
  description: 'Dashboard for visualizing LLM chain processing results',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
```

## web/src/app/pages.js

```
import Dashboard from '../components/Dashboard'

export default function Home() {
  return (
    <main>
      <Dashboard />
    </main>
  )
}
```

## web/src/components/Dashboard.jsx

```
import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const Dashboard = () => {
  const [chainResults, setChainResults] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:8000/llm_results');
        const data = await response.json();
        setChainResults(data);
      } catch (error) {
        console.error('Error fetching data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 1000); // refresh every 1 second
    return () => clearInterval(interval);
  }, []);

  const prepareExecutionTimeData = () => {
    return Object.entries(chainResults).map(([chainId, steps]) => ({
      chainId,
      ...steps.reduce((acc, step) => {
        acc[`Step ${step.step_number}`] = step.execution_time_ms;
        return acc;
      }, {})
    }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-lg">Loading data...</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold mb-6">LLM Chain Results Dashboard</h1>
      
      {/* 実行時間グラフ */}
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Execution Time by Chain and Step</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-96">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={prepareExecutionTimeData()}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="chainId" />
                <YAxis label={{ value: 'Execution Time (ms)', angle: -90, position: 'insideLeft' }} />
                <Tooltip />
                <Line type="monotone" dataKey="Step 1" stroke="#8884d8" />
                <Line type="monotone" dataKey="Step 2" stroke="#82ca9d" />
                <Line type="monotone" dataKey="Step 3" stroke="#ffc658" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* チェーン結果一覧 */}
      <div className="space-y-4">
        {Object.entries(chainResults).map(([chainId, steps]) => (
          <Card key={chainId} className="w-full">
            <CardHeader>
              <CardTitle>Chain ID: {chainId}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {steps.map((step) => (
                  <div key={step.task_id} className="border-l-4 border-blue-500 pl-4">
                    <h3 className="font-semibold">Step {step.step_number}</h3>
                    <div className="grid grid-cols-2 gap-4 mt-2">
                      <div>
                        <p className="text-sm font-medium">Prompt:</p>
                        <p className="text-sm mt-1">{step.prompt}</p>
                      </div>
                      <div>
                        <p className="text-sm font-medium">Response:</p>
                        <p className="text-sm mt-1">{step.response || step.error_message}</p>
                      </div>
                    </div>
                    <div className="mt-2 text-sm text-gray-500">
                      <span>Status: {step.status}</span>
                      <span className="ml-4">Execution Time: {step.execution_time_ms}ms</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default Dashboard;
```

## web/next.config.js

```
/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: 'http://api:8000/:path*',
        },
      ]
    }
  }
  
  module.exports = nextConfig
```

## web/package.json

```
{
  "name": "llm-dashboard",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "^14.1.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "recharts": "^2.12.0",
    "@radix-ui/react-slot": "^1.0.2",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwindcss-animate": "^1.0.7",
    "lucide-react": "^0.323.0",
    "tailwindcss": "^3.4.1",
    "postcss": "^8.4.35",
    "autoprefixer": "^10.4.17"
  }
}

```

## web/postcss.config.js

```
module.exports = {
    plugins: {
      tailwindcss: {},
      autoprefixer: {},
    },
  }
```

## web/tailwind.config.js

```
/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
      './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
      './src/components/**/*.{js,ts,jsx,tsx,mdx}',
      './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    ],
    theme: {
      extend: {},
    },
    plugins: [],
  }
```

## .env.example

```
# .env
POSTGRES_URL=postgresql://user:password@localhost/dbname
AZURE_API_KEY="api-key"
AZURE_ENDPOINT=https://test-o1-dev.openai.azure.com/
API_VERSION=2024-08-01-preview
OPENAI_MODEL=gpt-4o
REDIS_BROKER_URL=redis://localhost:6379/0
CELERY_BACKEND_URL=redis://localhost:6379/0
```

## Dockerfile

```
FROM python:3.12-slim

WORKDIR /app

# Set PYTHONPATH to include the working directory
ENV PYTHONPATH=/app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends bash postgresql-client \
    && echo 'alias ll="ls -laF"' >> /root/.bashrc \
    && echo 'alias ls="ls --color=auto"' >> /root/.bashrc \
    && echo 'export TERM=xterm-256color' >> /root/.bashrc

COPY app/ ./app
COPY config/ ./config
COPY alembic/ ./alembic
COPY alembic.ini .
COPY setup_path.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh", "api"]

```

## Dockerfile.web

```
FROM node:23-slim

WORKDIR /app/web

# Copy package.json and package-lock.json first for better caching
COPY web/package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY web/ .

# Build the Next.js application
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "dev"]
```

## alembic.ini

```
[alembic]
script_location = alembic
sqlalchemy.url = %(POSTGRES_URL)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s

```

## docker-compose.yml

```
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: api
    command: ["./entrypoint.sh", "api"]
    ports:
      - "8000:8000"
    volumes:
      - ./app/data/:/app/data
    depends_on:
      - db
      - redis
    environment:
      - POSTGRES_URL=postgresql://postgres:postgres@db/postgres
      - AZURE_API_KEY=${AZURE_API_KEY}
      - AZURE_ENDPOINT=${AZURE_ENDPOINT}
      - API_VERSION=${API_VERSION}
      - OPENAI_MODEL=${OPENAI_MODEL}
      - REDIS_BROKER_URL=redis://redis:6379/0
      - CELERY_BACKEND_URL=redis://redis:6379/0
      - LLM_TEMPERATURE=${LLM_TEMPERATURE:-0.2}
      - LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-1024}
      - LLM_TOP_P=${LLM_TOP_P:-0.95}
      - LLM_FREQUENCY_PENALTY=${LLM_FREQUENCY_PENALTY:-0.0}
      - LLM_PRESENCE_PENALTY=${LLM_PRESENCE_PENALTY:-0.0}

  celery:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: celery
    command: ["./entrypoint.sh", "celery"]
    depends_on:
      - db
      - redis
    environment:
      - POSTGRES_URL=postgresql://postgres:postgres@db/postgres
      - AZURE_API_KEY=${AZURE_API_KEY}
      - AZURE_ENDPOINT=${AZURE_ENDPOINT}
      - API_VERSION=${API_VERSION}
      - OPENAI_MODEL=${OPENAI_MODEL}
      - REDIS_BROKER_URL=redis://redis:6379/0
      - CELERY_BACKEND_URL=redis://redis:6379/0
      - LLM_TEMPERATURE=${LLM_TEMPERATURE:-0.2}
      - LLM_MAX_TOKENS=${LLM_MAX_TOKENS:-1024}
      - LLM_TOP_P=${LLM_TOP_P:-0.95}
      - LLM_FREQUENCY_PENALTY=${LLM_FREQUENCY_PENALTY:-0.0}
      - LLM_PRESENCE_PENALTY=${LLM_PRESENCE_PENALTY:-0.0}

  db:
    image: postgres:latest
    container_name: postgres
    restart: always
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: postgres
    ports:
      - "5432:5432"
    volumes:
      - ./db/postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:latest
    container_name: redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  web:
      build:
        context: .
        dockerfile: Dockerfile.web
      container_name: web
      ports:
        - "3000:3000"
      depends_on:
        - api

volumes:
  redis_data:

```

## entrypoint.sh

```
#!/bin/bash
set -e

# Wait for Postgres to be ready
echo "Waiting for Postgres to be ready..."
while ! pg_isready -h db -p 5432; do
  sleep 1
done
echo "Postgres is ready."

if [ "$1" == "api" ]; then
  echo "Running Alembic migrations..."
  alembic upgrade head
  echo "Starting Uvicorn server..."
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
elif [ "$1" == "celery" ]; then
  echo "Starting Celery worker..."
  exec celery -A app.tasks.celery_app worker --loglevel=info
else
  echo "Invalid argument. Use 'api' or 'celery'."
  exit 1
fi

```

## requirements.txt

```
# Core dependencies
python-dotenv
pydantic
pydantic-settings

# LLM API Client & Retry
openai
tenacity

# Data processing
pandas

# Database
sqlalchemy
alembic
psycopg2-binary

# Task Queue
celery
redis

# Web Framework
fastapi
uvicorn

# UUID
shortuuid

```

## setup_path.py

```
# setup_path.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

```

