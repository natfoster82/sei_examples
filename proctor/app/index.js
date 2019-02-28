// browser compatibility
import './js/fills';
import 'es6-shim';

// core
import React from 'react';
import ReactDOM from 'react-dom';

import { AppContainer } from 'react-hot-loader';

// Main component
import App from './App';

const render = Component => {
  ReactDOM.render(
    <AppContainer>
      <Component />
    </AppContainer>, document.getElementById('App')
  );
}

render(App)

// Hot Module Replacement API
if (module.hot) {
  module.hot.accept('./App', () => {
    const NewApp = require('./App').default
    render(NewApp);
  });
}
