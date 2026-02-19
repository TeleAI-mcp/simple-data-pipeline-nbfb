from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, Union, cast

from fastapi import routing
from fastapi.encoders import DictIntStrAny, SetIntStr
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.openapi.utils import get_openapi
from fastapi.params import Depends
from starlette.applications import Starlette
from starlette.datastructures import State
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Mount
from starlette.types import ASGIApp, Receive, Scope, Send


class FastAPI(Starlette):
    def __init__(
        self,
        *,
        debug: bool = False,
        routes: Optional[List[BaseRoute]] = None,
        title: str = "FastAPI",
        description: str = "",
        version: str = "0.1.0",
        openapi_url: Optional[str] = "/openapi.json",
        openapi_tags: Optional[List[Dict[str, Any]]] = None,
        servers: Optional[List[Dict[str, Union[str, Any]]]] = None,
        dependencies: Optional[Sequence[Depends]] = None,
        default_response_class: Type[Response] = JSONResponse,
        docs_url: Optional[str] = "/docs",
        redoc_url: Optional[str] = "/redoc",
        swagger_ui_oauth2_redirect_url: Optional[str] = "/docs/oauth2-redirect",
        swagger_ui_init_oauth: Optional[Dict[str, Any]] = None,
        middleware: Optional[Sequence[Middleware]] = None,
        exception_handlers: Optional[
            Dict[Union[int, Type[Exception]], Any]
        ] = None,
        on_startup: Optional[Sequence[Callable[[], Any]]] = None,
        on_shutdown: Optional[Sequence[Callable[[], Any]]] = None,
        terms_of_service: Optional[str] = None,
        contact: Optional[Dict[str, Union[str, Any]]] = None,
        license_info: Optional[Dict[str, Union[str, Any]]] = None,
        openapi_prefix: str = "",
        root_path: str = "",
        root_path_in_servers: bool = True,
        responses: Optional[Dict[Union[int, str], Dict[str, Any]]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None,
        webhooks: Optional[routing.APIRouter] = None,
        deprecated: Optional[bool] = None,
        include_in_schema: bool = True,
        swagger_ui_parameters: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        self._debug: bool = debug
        self.state: State = State()
        self.router: routing.APIRouter = routing.APIRouter(
            routes=routes,
            dependency_overrides_provider=self,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            default_response_class=default_response_class,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            responses=responses,
            callbacks=callbacks,
            webhooks=webhooks,
        )
        self.title = title
        self.description = description
        self.version = version
        self.terms_of_service = terms_of_service
        self.contact = contact
        self.license_info = license_info
        self.openapi_url = openapi_url
        self.openapi_tags = openapi_tags
        self.servers = servers or []
        self.root_path = root_path
        self.root_path_in_servers = root_path_in_servers
        self.dependencies = list(dependencies or [])
        self.middleware = list(middleware or [])
        self.exception_handlers: Dict[
            Union[int, Type[Exception]], Any
        ] = dict(exception_handlers or {})
        self.user_middleware: List[Middleware] = []
        self.default_response_class = default_response_class
        self._openapi_schema: Optional[Dict[str, Any]] = None
        self.docs_url = docs_url
        self.redoc_url = redoc_url
        self.swagger_ui_oauth2_redirect_url = swagger_ui_oauth2_redirect_url
        self.swagger_ui_init_oauth = swagger_ui_init_oauth
        self.openapi_prefix = openapi_prefix
        self.swagger_ui_parameters = swagger_ui_parameters
        self.extra = extra

        self.setup()

    def setup(self) -> None:
        if not self.routes:
            self.routes: List[BaseRoute] = []

        # Setup exception handlers
        self.add_exception_handler(StarletteHTTPException, http_exception_handler)
        self.add_exception_handler(
            RequestValidationError, request_validation_exception_handler
        )

        # Setup OpenAPI
        if self.openapi_url:
            assert (
                isinstance(self.openapi_url, str) and self.openapi_url.endswith(".json")
            ), "openapi_url must end with '.json'"
            self.add_route(
                self.openapi_url, lambda r: JSONResponse(self.openapi()), include_in_schema=False
            )

        # Setup docs
        if self.docs_url:
            assert isinstance(self.docs_url, str), "docs_url must be a string"
            self.add_route(
                self.docs_url,
                lambda r: get_swagger_ui_html(
                    openapi_url=self.openapi_url,
                    title=self.title + " - Swagger UI",
                    oauth2_redirect_url=self.swagger_ui_oauth2_redirect_url,
                    init_oauth=self.swagger_ui_init_oauth,
                    swagger_ui_parameters=self.swagger_ui_parameters,
                ),
                include_in_schema=False,
            )
            if self.swagger_ui_oauth2_redirect_url:
                self.add_route(
                    self.swagger_ui_oauth2_redirect_url,
                    lambda r: get_swagger_ui_oauth2_redirect_html(),
                    include_in_schema=False,
                )

        # Setup Redoc
        if self.redoc_url:
            assert isinstance(self.redoc_url, str), "redoc_url must be a string"
            self.add_route(
                self.redoc_url,
                lambda r: get_redoc_html(
                    openapi_url=self.openapi_url, title=self.title + " - ReDoc"
                ),
                include_in_schema=False,
            )

        # Add routes
        self.routes.extend(self.router.routes)

        # Add middleware
        self.add_middleware(ServerErrorMiddleware, debug=self._debug)
        for middleware in self.middleware:
            self.add_middleware(
                middleware.cls, **middleware.options  # type: ignore
            )
        for middleware in reversed(self.user_middleware):
            self.add_middleware(
                middleware.cls, **middleware.options  # type: ignore
            )

    def openapi(self) -> Dict[str, Any]:
        if not self.openapi_url:
            raise RuntimeError("The OpenAPI URL is not set, it was disabled.")
        if self._openapi_schema:
            return self._openapi_schema
        self._openapi_schema = get_openapi(
            title=self.title,
            version=self.version,
            description=self.description,
            routes=self.routes,
            tags=self.openapi_tags,
            servers=self.servers,
            terms_of_service=self.terms_of_service,
            contact=self.contact,
            license_info=self.license_info,
            webhooks=self.router.webhooks,
        )
        return self._openapi_schema

    def include_router(
        self,
        router: routing.APIRouter,
        *,
        prefix: str = "",
        tags: Optional[List[Union[str, Dict[str, Any]]]] = None,
        dependencies: Optional[Sequence[Depends]] = None,
        responses: Optional[Dict[Union[int, str], Dict[str, Any]]] = None,
        deprecated: Optional[bool] = None,
        include_in_schema: bool = True,
        default_response_class: Optional[Type[Response]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None,
        generate_unique_id_function: Optional[Callable[[routing.APIRoute], str]] = None,
    ) -> None:
        self.router.include_router(
            router,
            prefix=prefix,
            tags=tags,
            dependencies=dependencies,
            responses=responses,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            default_response_class=default_response_class,
            callbacks=callbacks,
            generate_unique_id_function=generate_unique_id_function,
        )

    def get(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.put(path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.delete(path, **kwargs)

    def options(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.options(path, **kwargs)

    def head(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.head(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.patch(path, **kwargs)

    def trace(self, path: str, **kwargs: Any) -> Callable[[DecoratedCallable], DecoratedCallable]:
        return self.router.trace(path, **kwargs)

    def add_middleware(self, middleware_class: Type[Middleware], **kwargs: Any) -> None:
        self.user_middleware.insert(0, Middleware(middleware_class, **kwargs))

    def add_exception_handler(
        self,
        exc_class_or_status_code: Union[int, Type[Exception]],
        handler: Callable[[Request, Any], Response],
    ) -> None:
        self.exception_handlers[exc_class_or_status_code] = handler

    def add_event_handler(self, event_type: str, func: Callable[[], Any]) -> None:
        assert event_type in ("startup", "shutdown"), "event_type must be 'startup' or 'shutdown'"
        if event_type == "startup":
            self.router.on_startup.append(func)
        else:
            self.router.on_shutdown.append(func)

    def add_route(
        self,
        path: str,
        route: Union[Type[ASGIApp], ASGIApp],
        *,
        methods: Optional[List[str]] = None,
        name: Optional[str] = None,
        include_in_schema: bool = True,
    ) -> None:
        self.router.add_route(
            path, route, methods=methods, name=name, include_in_schema=include_in_schema
        )

    def add_websocket_route(
        self,
        path: str,
        route: Union[Type[ASGIApp], ASGIApp],
        *,
        name: Optional[str] = None,
    ) -> None:
        self.router.add_websocket_route(path, route, name=name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope["app"] = self
        await super().__call__(scope, receive, send)

    def mount(self, path: str, app: ASGIApp, name: Optional[str] = None) -> None:
        route = Mount(path, app=app, name=name)
        self.routes.append(route)
