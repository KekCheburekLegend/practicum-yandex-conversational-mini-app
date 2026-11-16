# Архитектура Conversational Mini-App Studio

Данный документ описывает техническую архитектуру платформы, стек технологий, схему базы данных и ключевые архитектурные решения


## 


**Технологический стек:**
*   **Backend:** Python 3.11+, FastAPI, Pydantic
*   **Базы данных:** PostgreSQL, Redis
*   **Frontend:** 
*   **Инфраструктура:** Docker, Docker Compose, GitHub Actions.

### **обоснование выбора стека**

#### **Python**
* **Скорость разработки**
* **Асинхронность:** поддержка `async/await` позволяет не блокировать запросы и простого ожидания
* **автоматическая документация:** Автогенерация документации API (Swagger)

#### **PostgreSQL**
* **Надежность (ACID)**
* **Поддержка формата JSONB**

#### **Redis**
* **кэш:** снижение обращение в БД для поиска постоянной информации, что снижает нагрузку на CPU

## 2. Диаграмма компонентов

```mermaid
flowchart TD
    subgraph Frontend [Frontend]
        Chat[Chat Shell & Inspect Panel]
        Renderer[Schema Renderer]
        MiniApps[Mini-Apps: Research, Planner, Explorer]
    end

    subgraph Backend [Backend: FastAPI Modular Monolith]
        API[API Routers /api]
        RouterModule[Router Module /routing]
        RuntimeModule[Runtime Module /runtime]
        RegistryModule[Registry Module /registry]
        AuditModule[Audit Module /audit]
    end

    subgraph Data [Data Layer]
        PG[(PostgreSQL)]
        Redis[(Redis Cache)]
    end

    %% Connections
    Chat -->|HTTP/REST| API
    Renderer -->|JSON UI Schema| Chat
    MiniApps <-->|State Handoff| Renderer
    
    API --> RouterModule
    API --> RuntimeModule
    API --> RegistryModule
    
    RouterModule -->|Кэш маршрутов| Redis
    RuntimeModule -->|Сохранение State Envelope| PG
    AuditModule -->|Запись событий| PG
    RegistryModule -->|Чтение манифестов| API
```