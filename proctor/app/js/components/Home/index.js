// Core
import React from 'react';
import css from './style.scss';

class Home extends React.Component {
  render() {
    return (
      <div>
        <article className={ css.Home }>
          <p className={ css.p }>
            Home Page
          </p>
        </article>
      </div>
    )
  }
}

export default Home;